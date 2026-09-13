using System.Globalization;
using System.Text.Json;

namespace Bmg.Intake;

public sealed class FileResultRepository(string root) : IResultRepository
{
    private string PathFor(string id) => Path.Combine(root, "simulated-cosmos", id + ".json");
    public void Put(string id, Result value)
    {
        var path = PathFor(id);
        if (File.Exists(path))
        {
            if (JsonSerializer.Serialize(Get(id), Json.Options) != JsonSerializer.Serialize(value, Json.Options))
                throw new PermanentFailure("RepositoryConflict");
            return;
        }
        Json.Write(path, value);
    }
    public Result Get(string id) => Json.Read<Result>(PathFor(id));
}

public sealed class SimulatedPipeline : IPipelineAdapter
{
    private readonly Settings settings;
    private readonly IResultRepository repository;
    private readonly Policy policy;
    public SimulatedPipeline(Settings settings, IResultRepository repository)
    {
        this.settings = settings; this.repository = repository;
        // Stage A policy includes explanatory properties. Read just the operative contract.
        using var doc = JsonDocument.Parse(File.ReadAllText(settings.PolicyPath));
        var fields = new Dictionary<string, FieldRule>();
        foreach (var p in doc.RootElement.GetProperty("fields").EnumerateObject())
        {
            var v = p.Value;
            fields.Add(p.Name, new(v.GetProperty("required").GetBoolean(),
                v.GetProperty("sourcePriority").EnumerateArray().Select(x => x.GetString()!).ToArray(),
                v.TryGetProperty("allowedValues", out var choices) ? choices.EnumerateArray().Select(x => x.GetString()!).ToArray() : null,
                v.TryGetProperty("format", out var format) ? format.GetString() : null));
        }
        policy = new(fields, doc.RootElement.GetProperty("classificationThreshold").GetDouble());
    }
    public static string ResultName(Job j) => $"{j.SubmissionId}-r{j.Revision}-{j.Id[..8]}.json";
    public Task ExecuteAsync(int stage, Job job, Submission m, CancellationToken cancellation)
    {
        cancellation.ThrowIfCancellationRequested();
        string name = Stages.Names[stage];
        string artifactRoot = Path.Combine(job.Snapshot, "artifacts");
        Directory.CreateDirectory(artifactRoot);
        string artifact(string file) => Path.Combine(artifactRoot, file);
        if (settings.AlwaysFailStage == name) throw new IOException("Injected transient failure");
        if (settings.FailOnceStage == name)
        {
            string marker = Path.Combine(settings.Root, "state", job.Id + "-" + name + "-fault-used");
            if (!File.Exists(marker)) { File.WriteAllText(marker, "simulated test fault"); throw new IOException("Injected transient failure"); }
        }
        switch (name)
        {
            case "CredentialReady":
                if (!File.Exists(artifact("simulation-fixture.json")))
                {
                    string fixturePath = Path.Combine(settings.Root, "fixtures", $"{m.SubmissionId}-r{m.Revision}.json");
                    if (!File.Exists(fixturePath)) throw new PermanentFailure("SimulationFixtureMissing");
                    Fixture fixture = Json.Read<Fixture>(fixturePath);
                    if (fixture.ExecutionMode != "Simulated" || fixture.Metadata is null || fixture.DocumentTypes is null)
                        throw new PermanentFailure("InvalidSimulationFixture");
                    Json.Write(artifact("simulation-fixture.json"), fixture);
                }
                Json.Write(artifact("credentials.json"), new { executionMode = "Simulated", credentialsFetched = false });
                break;
            case "Uploaded":
                foreach (var d in m.Documents)
                {
                    string target = Path.Combine(settings.Root, "simulated-blob", job.Id, d.FileName);
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    if (File.Exists(target))
                    {
                        if (Intake.Hash(Intake.ReadLocked(target, 50 * 1024 * 1024)) != d.Sha256)
                            throw new PermanentFailure("UploadTargetConflict");
                        continue;
                    }
                    var bytes = Intake.ReadLocked(Path.Combine(job.Snapshot, d.FileName), 50 * 1024 * 1024);
                    if (Intake.Hash(bytes) != d.Sha256) throw new PermanentFailure("SnapshotIntegrityFailure");
                    string pending = target + ".tmp";
                    using (var stream = new FileStream(pending, FileMode.Create, FileAccess.Write, FileShare.None))
                    { stream.Write(bytes); stream.Flush(true); }
                    File.Move(pending, target, overwrite: false);
                }
                break;
            case "Classified":
                var classes = Json.Read<Fixture>(artifact("simulation-fixture.json")).DocumentTypes;
                string[] accepted = ["Note", "DeedOfTrust", "TitleCommitment", "Survey", "ClosingInstructions", "Rider"];
                if (m.Documents.Any(d => !classes.TryGetValue(d.DocumentId, out var type) || !accepted.Contains(type)))
                    throw new PermanentFailure("UnknownDocumentClass");
                if (policy.ClassificationThreshold > 0.99) throw new PermanentFailure("ClassificationBelowThreshold");
                Json.Write(artifact("classification.json"), new { executionMode = "Simulated", modelId = "simulation-fixture-v1", documents = classes, confidence = 0.99 });
                break;
            case "LayoutRead":
                Json.Write(artifact("layout.json"), new { executionMode = "Simulated", ocrPerformed = false, note = "Fixture mode; no document reading or OCR inference has occurred." });
                break;
            case "MetadataExtracted":
                Json.Write(artifact("candidates.json"), Json.Read<Fixture>(artifact("simulation-fixture.json")));
                break;
            case "MetadataValidated":
                Result result = Validate(m, Json.Read<Fixture>(artifact("candidates.json")));
                Json.Write(artifact("result.json"), result);
                if (result.ValidationErrors.Length > 0)
                {
                    Json.Write(Path.Combine(settings.Root, "results", ResultName(job)), result);
                    throw new PermanentFailure("MetadataValidationFailed");
                }
                break;
            case "Persisted": repository.Put(job.Id, Json.Read<Result>(artifact("result.json"))); break;
            case "Returned":
                Result stored = repository.Get(job.Id);
                if (stored.SubmissionId != m.SubmissionId || stored.Revision != m.Revision || stored.ExecutionMode != "Simulated"
                    || stored.Status != "Validated" || stored.ValidationErrors.Length != 0
                    || JsonSerializer.Serialize(stored, Json.Options) != JsonSerializer.Serialize(Json.Read<Result>(artifact("result.json")), Json.Options))
                    throw new PermanentFailure("ResultReadBackMismatch");
                Json.Write(Path.Combine(settings.Root, "results", ResultName(job)), stored);
                Json.Write(Path.Combine(settings.Root, "completed", job.Id + ".json"), new { executionMode = "Simulated", m.SubmissionId, m.Revision, resultFile = ResultName(job), job.Digest });
                break;
            default: throw new InvalidOperationException("Unexpected pipeline stage.");
        }
        return Task.CompletedTask;
    }
    private Result Validate(Submission m, Fixture f)
    {
        var metadata = new Dictionary<string, string?>(); var evidence = new List<Evidence>(); var errors = new List<string>();
        foreach (var (field, rule) in policy.Fields)
        {
            f.Metadata.TryGetValue(field, out var raw); string? value = string.IsNullOrWhiteSpace(raw) ? null : raw.Trim();
            if (field == "submissionType")
            {
                if (value is not null && value != m.SubmissionType) errors.Add(field + ":ManifestConflict");
                value = m.SubmissionType;
            }
            metadata[field] = value;
            if (rule.Required && value is null) errors.Add(field + ":Required");
            if (value is not null && rule.AllowedValues is not null && !rule.AllowedValues.Contains(value))
            { errors.Add(field + ":NotAllowed"); metadata[field] = null; continue; }
            if (value is not null && rule.Format == "date" && !DateOnly.TryParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _))
            { errors.Add(field + ":InvalidDate"); metadata[field] = null; continue; }
            if (value is null) continue;
            if (field == "submissionType") evidence.Add(new(field, "Manifest", null, null, value, null, null));
            else
            {
                var source = rule.SourcePriority.SelectMany(type => m.Documents.Where(d => f.DocumentTypes.GetValueOrDefault(d.DocumentId) == type)).FirstOrDefault();
                if (source is null) errors.Add(field + ":SourceMissing");
                else evidence.Add(new(field, "Document", source.DocumentId, 1,
                    "SIMULATED FIXTURE VALUE; NOT OCR EVIDENCE: " + value, "simulation-fixture-v1", "simulation-v1"));
            }
        }
        return new("poc-1", m.SubmissionId, m.Revision, errors.Count == 0 ? "Validated" : "ManualException", metadata, evidence.ToArray(), errors.ToArray());
    }
}
