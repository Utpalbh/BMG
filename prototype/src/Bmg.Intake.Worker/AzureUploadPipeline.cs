using System.Diagnostics;
using System.Net;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using Azure;
using Azure.Core;
using Azure.Identity;
using Azure.Security.KeyVault.Secrets;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;

namespace Bmg.Intake;

public sealed record AzureUploadConfiguration(string TenantId, string WorkerClientId,
    string WorkerCertificateThumbprint, string KeyVaultUri, string UploaderSecretName,
    string UploaderClientId, string BlobServiceUri, string Container, string AzCopyPath, string AzCopySha256)
{
    public string RuntimeBinding()
    {
        foreach (var id in new[] { TenantId, WorkerClientId, UploaderClientId })
            if (!Guid.TryParse(id, out _)) throw new ArgumentException("Invalid Azure identity ID.");
        ValidateEndpoint(KeyVaultUri, ".vault.azure.net");
        ValidateEndpoint(BlobServiceUri, ".blob.core.windows.net");
        if (Container != "submissions" || UploaderSecretName != "bmg-uploader-client-secret")
            throw new ArgumentException("Stage D is restricted to its submissions container and named uploader secret.");
        return "AzureUpload:" + Intake.Hash(Encoding.UTF8.GetBytes(string.Join('|', TenantId, WorkerClientId,
            UploaderClientId, KeyVaultUri, UploaderSecretName, BlobServiceUri, Container)));
    }
    private static void ValidateEndpoint(string endpoint, string suffix)
    {
        if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || uri.Scheme != "https"
            || uri.Port != 443 || !uri.Host.EndsWith(suffix, StringComparison.OrdinalIgnoreCase)
            || uri.AbsolutePath != "/" || uri.Query != "" || uri.Fragment != "" || uri.UserInfo != "")
            throw new ArgumentException("Invalid Azure service endpoint.");
    }
}

public sealed class AzureUploadPipeline : IPipelineAdapter, IDisposable
{
    private readonly Settings settings;
    private readonly AzureUploadConfiguration config;
    private readonly X509Certificate2 certificate;
    private readonly ClientCertificateCredential workerCredential;
    internal TokenCredential WorkerCredential => workerCredential;
    private readonly SecretClient vault;
    private string? uploaderSecret;
    private ClientSecretCredential? uploaderCredential;
    private DateTimeOffset secretExpiry;
    private string? secretVersion;

    public AzureUploadPipeline(Settings settings, AzureUploadConfiguration config)
    {
        this.settings = settings; this.config = config;
        config.RuntimeBinding();
        if (!Path.IsPathFullyQualified(config.AzCopyPath) || !File.Exists(config.AzCopyPath)
            || Intake.Hash(File.ReadAllBytes(config.AzCopyPath)) != config.AzCopySha256)
            throw new ArgumentException("Pinned AzCopy executable integrity check failed.");
        using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
        store.Open(OpenFlags.ReadOnly);
        var matches = store.Certificates.Find(X509FindType.FindByThumbprint, config.WorkerCertificateThumbprint, false);
        if (matches.Count != 1 || !matches[0].HasPrivateKey || matches[0].NotAfter.ToUniversalTime() <= DateTime.UtcNow)
            throw new ArgumentException("Worker certificate is missing, expired or has no private key.");
        certificate = matches[0];
        // Deterministic application credentials: never fall back to developer/CLI credentials.
        workerCredential = new ClientCertificateCredential(config.TenantId, config.WorkerClientId, certificate);
        var options = new SecretClientOptions();
        options.Retry.MaxRetries = 2; options.Retry.NetworkTimeout = TimeSpan.FromSeconds(20);
        vault = new SecretClient(new Uri(config.KeyVaultUri), workerCredential, options);
    }

    private static async Task RequirePrivateDns(string endpoint, CancellationToken cancellation)
    {
        IPAddress[] addresses = await Dns.GetHostAddressesAsync(new Uri(endpoint).Host, cancellation);
        if (addresses.Length == 0 || addresses.Any(a => !a.ToString().StartsWith("10.84.1.", StringComparison.Ordinal)))
            throw new IOException("PrivateDnsUnavailable");
    }

    private async Task EnsureUploader(CancellationToken cancellation, bool force = false)
    {
        if (!force && uploaderCredential is not null && secretExpiry > DateTimeOffset.UtcNow.AddMinutes(2)) return;
        await RequirePrivateDns(config.KeyVaultUri, cancellation);
        KeyVaultSecret secret = (await vault.GetSecretAsync(config.UploaderSecretName, cancellationToken: cancellation)).Value;
        if (secret.Properties.Enabled == false || secret.Properties.ExpiresOn is null
            || secret.Properties.ExpiresOn <= DateTimeOffset.UtcNow.AddMinutes(1)
            || !secret.Properties.Tags.TryGetValue("clientId", out var clientId) || clientId != config.UploaderClientId)
            throw new PermanentFailure("UploaderCredentialInvalidOrExpired");
        uploaderSecret = secret.Value;
        secretExpiry = secret.Properties.ExpiresOn.Value;
        secretVersion = secret.Properties.Version;
        uploaderCredential = new ClientSecretCredential(config.TenantId, config.UploaderClientId, uploaderSecret);
        await uploaderCredential.GetTokenAsync(new TokenRequestContext(["https://storage.azure.com/.default"]), cancellation);
    }

    private BlobClient Blob(string path, TokenCredential? credential = null)
    {
        var options = new BlobClientOptions();
        options.Retry.MaxRetries = 2; options.Retry.NetworkTimeout = TimeSpan.FromSeconds(20);
        return new BlobServiceClient(new Uri(config.BlobServiceUri), credential ?? uploaderCredential!, options)
            .GetBlobContainerClient(config.Container).GetBlobClient(path);
    }

    private async Task<(string Hash, string ETag, long Length)?> ReadRemote(BlobClient blob, CancellationToken cancellation)
    {
        BlobProperties properties;
        try { properties = (await blob.GetPropertiesAsync(cancellationToken: cancellation)).Value; }
        catch (RequestFailedException e) when (e.Status == 404) { return null; }
        if (properties.ContentLength > 50 * 1024 * 1024) throw new PermanentFailure("UnexpectedRemoteBlobSize");
        var download = await blob.DownloadStreamingAsync(new BlobDownloadOptions
        { Conditions = new BlobRequestConditions { IfMatch = properties.ETag } }, cancellation);
        using var content = download.Value.Content;
        string hash = Convert.ToHexStringLower(await SHA256.HashDataAsync(content, cancellation));
        return (hash, properties.ETag.ToString(), properties.ContentLength);
    }

    private async Task UploadWithAzCopy(string source, BlobClient blob, CancellationToken cancellation)
    {
        string telemetry = Path.Combine(settings.Root, "azcopy");
        Directory.CreateDirectory(telemetry); Intake.NoLink(telemetry);
        var start = new ProcessStartInfo(config.AzCopyPath)
        { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in new[] { "copy", source, blob.Uri.AbsoluteUri, "--from-to=LocalBlob", "--overwrite=false",
            "--check-length=true", "--put-md5", "--output-type=json", "--log-level=NONE" }) start.ArgumentList.Add(argument);
        foreach (var key in start.Environment.Keys.Where(k => k.StartsWith("AZCOPY_", StringComparison.OrdinalIgnoreCase)).ToArray())
            start.Environment.Remove(key);
        // Only this child receives the uploader secret; it is never a process argument or persisted job field.
        start.Environment["AZCOPY_AUTO_LOGIN_TYPE"] = "SPN";
        start.Environment["AZCOPY_SPA_APPLICATION_ID"] = config.UploaderClientId;
        start.Environment["AZCOPY_TENANT_ID"] = config.TenantId;
        start.Environment["AZCOPY_SPA_CLIENT_SECRET"] = uploaderSecret;
        start.Environment["AZCOPY_LOG_LOCATION"] = telemetry;
        start.Environment["AZCOPY_JOB_PLAN_LOCATION"] = telemetry;
        start.Environment["AZCOPY_CONCURRENCY_VALUE"] = "4";
        using var process = Process.Start(start) ?? throw new IOException("AzCopyStartFailed");
        start.Environment.Remove("AZCOPY_SPA_CLIENT_SECRET");
        // Drain output without persisting untrusted child output. Verified remote bytes determine success.
        Task output = process.StandardOutput.BaseStream.CopyToAsync(Stream.Null, CancellationToken.None);
        Task error = process.StandardError.BaseStream.CopyToAsync(Stream.Null, CancellationToken.None);
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        timeout.CancelAfter(TimeSpan.FromMinutes(3));
        try { await process.WaitForExitAsync(timeout.Token); }
        catch (OperationCanceledException)
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync(CancellationToken.None);
            if (cancellation.IsCancellationRequested) throw;
            throw new IOException("AzCopyTimedOut");
        }
        finally { await Task.WhenAll(output, error); }
        if (process.ExitCode != 0) throw new IOException("AzCopyFailed");
    }

    public async Task ExecuteAsync(int stage, Job job, Submission manifest, CancellationToken cancellation)
    {
        try
        {
            if (stage is < 1 or > 2) throw new PermanentFailure("StageDStopsAfterUpload");
            await EnsureUploader(cancellation, force: stage == 1);
            if (stage == 1)
            {
                Json.Write(Path.Combine(job.Snapshot, "azure-credential.json"), new { executionMode = "AzureUpload",
                    workerClientId = config.WorkerClientId, uploaderClientId = config.UploaderClientId,
                    secretName = config.UploaderSecretName, secretVersion, secretExpiry, authenticatedAt = DateTimeOffset.UtcNow });
                return;
            }
            await RequirePrivateDns(config.BlobServiceUri, cancellation);
            var files = manifest.Documents.Select(d => (d.FileName, Hash: d.Sha256))
                .Append(("submission.json", Intake.Hash(File.ReadAllBytes(Path.Combine(job.Snapshot, "submission.json")))));
            var receipts = new List<object>();
            foreach (var (fileName, expectedHash) in files)
            {
                cancellation.ThrowIfCancellationRequested();
                string path = $"{manifest.SubmissionId}/r{manifest.Revision}/{job.Digest}/{fileName}";
                var blob = Blob(path);
                var existing = await ReadRemote(blob, cancellation);
                if (existing is not null && existing.Value.Hash != expectedHash)
                    throw new PermanentFailure("RemoteContentConflict");
                bool reused = existing is not null;
                if (!reused) await UploadWithAzCopy(Path.Combine(job.Snapshot, fileName), blob, cancellation);
                var verified = reused ? existing : await ReadRemote(blob, cancellation);
                if (verified is null || verified.Value.Hash != expectedHash) throw new PermanentFailure("UploadReadBackMismatch");
                receipts.Add(new { blob = blob.Uri.AbsoluteUri, sha256 = verified.Value.Hash,
                    etag = verified.Value.ETag, length = verified.Value.Length, reused });
            }
            Json.Write(Path.Combine(job.Snapshot, "azure-upload.json"), new { executionMode = "AzureUpload",
                job.SubmissionId, job.Revision, job.Digest, status = "Uploaded", verifiedAt = DateTimeOffset.UtcNow,
                files = receipts, aiPerformed = false, cosmosWritten = false });
        }
        catch (AuthenticationFailedException) { throw new PermanentFailure("AzureApplicationAuthenticationFailed"); }
        catch (RequestFailedException e) when (e.Status is 401 or 403) { throw new PermanentFailure("AzureDataAccessDenied"); }
        catch (RequestFailedException e) when (e.Status is 408 or 429 or 0 || e.Status >= 500) { throw new IOException("AzureTransientFailure"); }
        catch (RequestFailedException) { throw new PermanentFailure("AzureRequestRejected"); }
        catch (System.Net.Sockets.SocketException) { throw new IOException("PrivateNetworkUnavailable"); }
        catch (HttpRequestException) { throw new IOException("AzureNetworkFailure"); }
    }

    public async Task<bool> VerifyIdentityAsync(CancellationToken cancellation)
    {
        await EnsureUploader(cancellation, force: true);
        await RequirePrivateDns(config.BlobServiceUri, cancellation);
        var outcomes = new Dictionary<string, bool> { ["workerReadsNamedSecret"] = true };
        await new BlobServiceClient(new Uri(config.BlobServiceUri), uploaderCredential!).GetBlobContainerClient(config.Container)
            .GetPropertiesAsync(cancellationToken: cancellation);
        outcomes["uploaderReadsSubmissionsContainer"] = true;
        async Task<bool> Denied(Func<Task> action)
        {
            try { await action(); return false; }
            catch (RequestFailedException e) when (e.Status == 403) { return true; }
        }
        outcomes["workerDeniedOtherSecret"] = await Denied(async () => { await vault.GetSecretAsync("bmg-not-authorized", cancellationToken: cancellation); });
        outcomes["workerDeniedBlob"] = await Denied(async () => { await Blob("scope-probe", workerCredential).GetPropertiesAsync(cancellationToken: cancellation); });
        outcomes["uploaderDeniedKeyVault"] = await Denied(async () => {
            await new SecretClient(new Uri(config.KeyVaultUri), uploaderCredential!).GetSecretAsync(config.UploaderSecretName, cancellationToken: cancellation);
        });
        outcomes["uploaderDeniedTrainingContainer"] = await Denied(async () => {
            await new BlobServiceClient(new Uri(config.BlobServiceUri), uploaderCredential!).GetBlobContainerClient("training")
                .GetPropertiesAsync(cancellationToken: cancellation);
        });
        bool passed = outcomes.Values.All(value => value);
        Json.Write(Path.Combine(settings.Root, "identity-verification.json"), new { timestamp = DateTimeOffset.UtcNow, executionMode = "AzureUpload", outcomes, allPassed = passed });
        foreach (var (name, value) in outcomes) Console.WriteLine($"{name}: {value}");
        return passed;
    }
    public void Dispose() { uploaderSecret = null; uploaderCredential = null; certificate.Dispose(); }
}
