using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Azure.Core;
using Azure.Identity;
using UglyToad.PdfPig;

namespace Bmg.Intake;

public sealed record AzureDocumentConfiguration(AzureUploadConfiguration Upload, string DocumentIntelligenceEndpoint,
    string ClassifierId, double ClassificationThreshold = 0.8, int MaximumDocumentPages = 20,
    int ClassificationPageBudget = 120, int LayoutPageBudget = 120)
{
    public string RuntimeBinding()
    {
        Upload.RuntimeBinding();
        if (!Uri.TryCreate(DocumentIntelligenceEndpoint, UriKind.Absolute, out var u) || u.Scheme != "https" || u.Port != 443
            || !u.Host.EndsWith(".cognitiveservices.azure.com", StringComparison.OrdinalIgnoreCase) || u.AbsolutePath != "/"
            || u.Query != "" || u.Fragment != "" || u.UserInfo != "") throw new ArgumentException("Invalid Document Intelligence endpoint.");
        if (!System.Text.RegularExpressions.Regex.IsMatch(ClassifierId, "^[a-zA-Z0-9][a-zA-Z0-9._~-]{1,63}$")
            || ClassificationThreshold is < 0.5 or > 1 || !double.IsFinite(ClassificationThreshold)
            || MaximumDocumentPages is < 1 or > 100 || ClassificationPageBudget is < 1 or > 240 || LayoutPageBudget is < 1 or > 240)
            throw new ArgumentException("Invalid classifier policy or page budget.");
        return "AzureDocuments:" + Intake.Hash(JsonSerializer.SerializeToUtf8Bytes(this, Json.Options));
    }
}
public sealed record ClassificationReceipt(string DocumentId, string Sha256, string ModelId, string DocumentType, double Confidence, int Pages, bool Accepted);

public sealed class AzureDocumentPipeline(Settings settings, AzureDocumentConfiguration config, AzureUploadPipeline upload, StateStore store) : IPipelineAdapter, IDisposable
{
    private const string Api = "2024-11-30";
    private static readonly string[] Allowed = ["Note", "DeedOfTrust", "TitleCommitment", "Survey", "ClosingInstructions", "Rider"];
    private readonly HttpClient http = new(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(60) };
    public async Task<bool> VerifyIdentityAsync(CancellationToken cancellation)
    {
        using var response = await Send(HttpMethod.Get, config.DocumentIntelligenceEndpoint.TrimEnd('/') + "/documentintelligence/documentClassifiers?api-version=" + Api, null, cancellation);
        bool passed = response.StatusCode == HttpStatusCode.OK;
        Json.Write(Path.Combine(settings.Root, "document-identity-verification.json"), new { workerClientId = config.Upload.WorkerClientId,
            privateDnsRequired = true, httpStatus = (int)response.StatusCode, workerCanReadClassifiers = passed, verifiedAt = DateTimeOffset.UtcNow });
        Console.WriteLine("workerCanReadClassifiers: " + passed);
        return passed;
    }
    private int PageCount(byte[] bytes)
    {
        try
        {
            using var pdf = PdfDocument.Open(bytes);
            if (pdf.IsEncrypted) throw new PermanentFailure("PdfMalformedOrEncrypted");
            int pages = pdf.NumberOfPages;
            if (pages < 1 || pages > config.MaximumDocumentPages) throw new PermanentFailure("PdfPageLimitExceeded");
            // Force parsing before invoking a paid service. Image-only pages are valid.
            foreach (var page in pdf.GetPages()) { _ = page.Width; _ = page.Height; }
            return pages;
        }
        catch (PermanentFailure) { throw; }
        catch (Exception e) when (e is not OutOfMemoryException) { throw new PermanentFailure("PdfMalformedOrEncrypted"); }
    }
    private async Task<HttpResponseMessage> Send(HttpMethod method, string url, object? body, CancellationToken cancellation)
    {
        var target = new Uri(url); var endpoint = new Uri(config.DocumentIntelligenceEndpoint);
        if (target.Scheme != "https" || target.Host != endpoint.Host || target.Port != 443 || target.UserInfo != ""
            || !target.AbsolutePath.StartsWith("/documentintelligence/", StringComparison.Ordinal)) throw new PermanentFailure("InvalidAiOperationLocation");
        var addresses = await Dns.GetHostAddressesAsync(target.Host, cancellation);
        if (addresses.Length == 0 || addresses.Any(a => !a.ToString().StartsWith("10.84.1.", StringComparison.Ordinal))) throw new IOException("PrivateDnsUnavailable");
        var token = await upload.WorkerCredential.GetTokenAsync(new TokenRequestContext(["https://cognitiveservices.azure.com/.default"]), cancellation);
        using var request = new HttpRequestMessage(method, target);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Token);
        if (body is not null) request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");
        return await http.SendAsync(request, cancellation);
    }
    private async Task<JsonElement> Analyze(Job job, Document document, string kind, CancellationToken cancellation)
    {
        byte[] bytes = File.ReadAllBytes(Path.Combine(job.Snapshot, document.FileName));
        if (Intake.Hash(bytes) != document.Sha256) throw new PermanentFailure("SnapshotContentChanged");
        int pages = PageCount(bytes);
        string model = kind == "classify" ? config.ClassifierId : "prebuilt-layout";
        string key = Intake.Hash(Encoding.UTF8.GetBytes($"{job.Id}|{document.DocumentId}|{document.Sha256}|{kind}|{model}|{Api}"));
        var saved = store.AiRequest(key);
        string? operation = saved?.Operation;
        string endpoint = config.DocumentIntelligenceEndpoint.TrimEnd('/');
        if (saved?.Status == "Succeeded") return JsonDocument.Parse(saved.Value.Result!).RootElement.Clone();
        if (saved?.Status is "Submitting" or "Rejected" or "Failed") throw new PermanentFailure(saved?.Status == "Submitting" ? "AiSubmissionOutcomeUnknown" : "AiRequestFailed");
        if (saved is null)
        {
            string path = kind == "classify" ? $"documentClassifiers/{model}:analyze?api-version={Api}&split=none" : $"documentModels/prebuilt-layout:analyze?api-version={Api}&stringIndexType=utf16CodeUnit";
            // Commit intent before POST. A crash in the response gap requires review instead of duplicate billing.
            store.ReserveAi(key, kind, pages, kind == "classify" ? config.ClassificationPageBudget : config.LayoutPageBudget);
            using var response = await Send(HttpMethod.Post, endpoint + "/documentintelligence/" + path, new { base64Source = Convert.ToBase64String(bytes) }, cancellation);
            if (response.StatusCode != HttpStatusCode.Accepted)
            {
                store.UpdateAi(key, "Rejected", null);
                throw new PermanentFailure("AiSubmitHttp" + (int)response.StatusCode);
            }
            if (!response.Headers.TryGetValues("Operation-Location", out var locations)) throw new PermanentFailure("AiSubmissionOutcomeUnknown");
            operation = locations.Single();
            store.UpdateAi(key, "Running", operation);
        }
        if (operation is null) throw new PermanentFailure("AiSubmissionOutcomeUnknown");
        for (int attempt = 0; attempt < 90; attempt++)
        {
            using var response = await Send(HttpMethod.Get, operation, null, cancellation);
            if ((int)response.StatusCode is 429 or 408 or >= 500) throw new IOException("AiPollTransientFailure");
            if (!response.IsSuccessStatusCode) throw new PermanentFailure("AiPollHttp" + (int)response.StatusCode);
            string raw = await response.Content.ReadAsStringAsync(cancellation);
            using var json = JsonDocument.Parse(raw);
            string? status = json.RootElement.GetProperty("status").GetString();
            if (status == "succeeded")
            {
                var result = json.RootElement.GetProperty("analyzeResult");
                if (result.GetProperty("apiVersion").GetString() != Api || result.GetProperty("modelId").GetString() != model) throw new PermanentFailure("AiResultModelMismatch");
                store.UpdateAi(key, "Succeeded", operation, result.GetRawText());
                return result.Clone();
            }
            if (status is "failed" or "canceled") { store.UpdateAi(key, "Failed", operation, raw); throw new PermanentFailure("AiAnalysisFailed"); }
            double delay = response.Headers.RetryAfter?.Delta?.TotalSeconds ?? 3;
            await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(delay, 1, 30)), cancellation);
        }
        throw new IOException("AiPollTimedOut");
    }
    public async Task ExecuteAsync(int stage, Job job, Submission manifest, CancellationToken cancellation)
    {
        try
        {
            if (stage <= 2)
            {
                foreach (var d in manifest.Documents) PageCount(File.ReadAllBytes(Path.Combine(job.Snapshot, d.FileName)));
                await upload.ExecuteAsync(stage, job, manifest, cancellation); return;
            }
            if (stage == 3)
            {
                var receipts = new List<ClassificationReceipt>();
                foreach (var d in manifest.Documents)
                {
                    var result = await Analyze(job, d, "classify", cancellation);
                    Json.Write(Path.Combine(job.Snapshot, "ai", d.DocumentId + "-classify.json"), result);
                    var docs = result.GetProperty("documents").EnumerateArray().ToArray();
                    if (docs.Length != 1) throw new PermanentFailure("UnexpectedDocumentSplit");
                    string label = docs[0].GetProperty("docType").GetString()!;
                    double confidence = docs[0].GetProperty("confidence").GetDouble();
                    receipts.Add(new(d.DocumentId, d.Sha256, config.ClassifierId, label, confidence,
                        PageCount(File.ReadAllBytes(Path.Combine(job.Snapshot, d.FileName))), Allowed.Contains(label) && confidence >= config.ClassificationThreshold));
                }
                Json.Write(Path.Combine(job.Snapshot, "classification.json"), receipts);
                if (receipts.Any(r => !r.Accepted)) throw new PermanentFailure("ClassificationRequiresReview");
                return;
            }
            if (stage == 4)
            {
                var summary = new List<object>();
                foreach (var d in manifest.Documents)
                {
                    var result = await Analyze(job, d, "layout", cancellation);
                    Json.Write(Path.Combine(job.Snapshot, "ai", d.DocumentId + "-layout.json"), result);
                    string text = result.GetProperty("content").GetString() ?? "";
                    if (string.IsNullOrWhiteSpace(text)) throw new PermanentFailure("NoReadableText");
                    int pages = result.GetProperty("pages").GetArrayLength();
                    if (pages != PageCount(File.ReadAllBytes(Path.Combine(job.Snapshot, d.FileName)))) throw new PermanentFailure("OcrPageCountMismatch");
                    summary.Add(new { d.DocumentId, d.Sha256, pages, characters = text.Length, modelId = "prebuilt-layout", evidenceFile = "ai/" + d.DocumentId + "-layout.json" });
                }
                Json.Write(Path.Combine(job.Snapshot, "layout-summary.json"), new { executionMode = settings.ExecutionMode, status = "LayoutRead", apiVersion = Api,
                    files = summary, llmPerformed = false, cosmosWritten = false, finalResultReturned = false });
                return;
            }
            throw new PermanentFailure("StageEStopsAfterLayout");
        }
        catch (AuthenticationFailedException) { throw new PermanentFailure("AzureApplicationAuthenticationFailed"); }
        catch (KeyNotFoundException) { throw new PermanentFailure("AiResponseMalformed"); }
        catch (InvalidOperationException) { throw new PermanentFailure("AiResponseMalformed"); }
        catch (HttpRequestException) { throw new IOException("AiNetworkFailure"); }
        catch (System.Net.Sockets.SocketException) { throw new IOException("PrivateNetworkUnavailable"); }
        catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { throw new IOException("AiNetworkTimeout"); }
    }
    public void Dispose() => http.Dispose();
}
