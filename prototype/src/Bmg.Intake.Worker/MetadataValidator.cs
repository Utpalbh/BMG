using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Bmg.Intake;

public sealed record FieldCandidate(string DocumentId, string Field, string? Value, int? Page, string? Quote);
public sealed record CandidateResponse(FieldCandidate[] Candidates);
public sealed record OcrPage(string DocumentId, int Page, string Text);

public sealed class MetadataValidator
{
    private static readonly Dictionary<string,string> Labels = new() {
        ["lenderCode"] = @"lender\s*code", ["loanNumber"] = @"loan\s*(?:number|no\.?|#)",
        ["borrowerName"] = @"borrower(?:\s*name)?", ["propertyAddress"] = @"property\s*address",
        ["closingDate"] = @"closing\s*date", ["loanType"] = @"loan\s*type", ["purpose"] = @"(?:loan\s*)?purpose"
    };
    public Dictionary<string, FieldRule> Fields { get; } = new();
    public MetadataValidator(string policyPath)
    {
        using var policy = JsonDocument.Parse(File.ReadAllText(policyPath));
        foreach (var p in policy.RootElement.GetProperty("fields").EnumerateObject())
        {
            var v = p.Value;
            Fields.Add(p.Name, new(v.GetProperty("required").GetBoolean(), v.GetProperty("sourcePriority").EnumerateArray().Select(x => x.GetString()!).ToArray(),
                v.TryGetProperty("allowedValues", out var a) ? a.EnumerateArray().Select(x => x.GetString()!).ToArray() : null,
                v.TryGetProperty("format", out var f) ? f.GetString() : null));
        }
    }
    public static string Normalize(string text) => Regex.Replace(text.Trim(), @"\s+", " ");
    public static string? NormalizeValue(string field, string value)
    {
        value = Normalize(value);
        if (field != "closingDate") return value;
        string[] formats = ["yyyy-MM-dd", "MMMM d, yyyy", "MMM d, yyyy", "MMMM dd, yyyy", "MMM dd, yyyy"];
        return DateOnly.TryParseExact(value, formats, CultureInfo.InvariantCulture, DateTimeStyles.None, out var date) ? date.ToString("yyyy-MM-dd") : null;
    }
    public Result Validate(Submission manifest, CandidateResponse response, ClassificationReceipt[] classes, OcrPage[] pages, string model, string prompt)
    {
        var errors = new List<string>(); var metadata = new Dictionary<string, string?>(); var evidence = new List<Evidence>();
        if (response.Candidates is null || response.Candidates.Length > manifest.Documents.Length * Fields.Count * 4) throw new PermanentFailure("CandidateContractInvalid");
        var candidates = response.Candidates;
        foreach (var c in candidates)
        {
            if (c is null || !manifest.Documents.Any(d => d.DocumentId == c.DocumentId) || !Fields.ContainsKey(c.Field) || c.Field == "submissionType")
                throw new PermanentFailure("CandidateContractInvalid");
        }
        foreach (var (field, rule) in Fields)
        {
            if (field == "submissionType")
            {
                metadata[field] = manifest.SubmissionType;
                if (rule.AllowedValues is not null && !rule.AllowedValues.Contains(manifest.SubmissionType)) errors.Add(field + ":NotAllowed");
                evidence.Add(new(field, "Manifest", null, null, manifest.SubmissionType, null, null)); continue;
            }
            var valid = new List<(FieldCandidate Candidate, string Value, int Priority)>();
            foreach (var document in manifest.Documents)
            {
                var entries = candidates.Where(c => c.Field == field && c.DocumentId == document.DocumentId).ToArray();
                // Every field/document pair must be explicitly assessed, including absent values.
                if (entries.Length == 0) { errors.Add(field + ":AssessmentMissing"); continue; }
                if (entries.Length > 1 && entries.Any(c => c.Value is null)) errors.Add(field + ":ContradictoryAssessment");
                foreach (var c in entries)
                {
                    if (c.Value is null)
                    {
                        if (c.Page is not null || c.Quote is not null) errors.Add(field + ":InvalidNullEvidence");
                        continue;
                    }
                    var source = classes.SingleOrDefault(x => x.DocumentId == c.DocumentId && x.Sha256 == document.Sha256 && x.Accepted);
                    var page = pages.SingleOrDefault(x => x.DocumentId == c.DocumentId && x.Page == c.Page);
                    string quote = c.Quote is null ? "" : Normalize(c.Quote);
                    string rawValue = Normalize(c.Value);
                    // A model may return the labelled OCR cell as its value. Strip only a recognized
                    // leading field label; the remaining value must still be supported by the quote.
                    if (Labels.TryGetValue(field, out var leadingLabel))
                        rawValue = Regex.Replace(rawValue, @"^(?:" + leadingLabel + @")\s*[:#=\-]?\s+", "", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
                    string? value = NormalizeValue(field, rawValue);
                    bool valueInQuote = rawValue.Length > 0 && Regex.IsMatch(quote, @"(?<![\p{L}\p{N}])" + Regex.Escape(rawValue) + @"(?![\p{L}\p{N}])", RegexOptions.CultureInvariant);
                    bool labelSupportsValue = Labels.TryGetValue(field, out var label) && Regex.IsMatch(quote,
                        @"\b(?:" + label + @")\s*[:#=\-]?\s*" + Regex.Escape(rawValue) + @"(?![\p{L}\p{N}])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
                    if (source is null || page is null || quote.Length == 0 || !Normalize(page.Text).Contains(quote, StringComparison.Ordinal) || !valueInQuote)
                    { errors.Add(field + ":EvidenceMismatch"); continue; }
                    if (!labelSupportsValue) { errors.Add(field + ":UnsupportedFieldLabel"); continue; }
                    if (value is null) { errors.Add(field + ":AmbiguousOrInvalidDate"); continue; }
                    if (rule.AllowedValues is not null && !rule.AllowedValues.Contains(value)) { errors.Add(field + ":NotAllowed"); continue; }
                    int priority = Array.IndexOf(rule.SourcePriority, source.DocumentType);
                    // Conflicts across all supplied documents remain visible, even outside preferred sources.
                    valid.Add((c, value, priority));
                }
            }
            var values = valid.Select(x => x.Value).Distinct(StringComparer.Ordinal).ToArray();
            if (values.Length > 1) errors.Add(field + ":Conflict");
            var preferred = valid.Where(x => x.Priority >= 0).OrderBy(x => x.Priority).ToArray();
            metadata[field] = values.Length == 1 && preferred.Length > 0 ? values[0] : null;
            if (metadata[field] is null && rule.Required) errors.Add(field + ":Required");
            if (metadata[field] is not null)
            {
                var c = preferred[0].Candidate;
                evidence.Add(new(field, "Document", c.DocumentId, c.Page, c.Quote!, model, prompt));
            }
        }
        return new("poc-1", manifest.SubmissionId, manifest.Revision, errors.Count == 0 ? "Validated" : "ManualException", metadata, evidence.ToArray(), errors.Distinct().ToArray(), "AzureFull");
    }
}
