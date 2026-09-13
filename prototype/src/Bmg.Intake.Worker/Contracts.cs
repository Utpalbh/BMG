using System.Text.Json;
using System.Text.Json.Serialization;

namespace Bmg.Intake;

public static class Json
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        PropertyNameCaseInsensitive = false
    };
    public static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Options)
        ?? throw new InvalidDataException("Empty JSON object.");
    public static void Write(string path, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temp = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, Options);
        using (var stream = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
        {
            stream.Write(bytes);
            stream.Flush(flushToDisk: true);
        }
        File.Move(temp, path, overwrite: true);
    }
}

public sealed record Document(string DocumentId, string FileName, string Sha256);
public sealed record Submission(string SchemaVersion, string SubmissionId, int Revision,
    string Source, string SubmissionType, Document[] Documents);
public sealed record Evidence(string Field, string SourceKind, string? DocumentId, int? Page,
    string EvidenceText, string? ModelId, string? PromptVersion);
public sealed record Result(string SchemaVersion, string SubmissionId, int Revision, string Status,
    Dictionary<string, string?> Metadata, Evidence[] Provenance, string[] ValidationErrors,
    string ExecutionMode = "Simulated");
public sealed record Fixture(string ExecutionMode, Dictionary<string, string?> Metadata,
    Dictionary<string, string> DocumentTypes);
public sealed record Policy(Dictionary<string, FieldRule> Fields, double ClassificationThreshold);
public sealed record FieldRule(bool Required, string[] SourcePriority, string[]? AllowedValues, string? Format);
public sealed record Job(string Id, string SubmissionId, int Revision, string Digest, string Snapshot,
    int Stage, string Status, int Attempts, long NextAttemptUtc, string? ErrorCode);

public static class Stages
{
    public static readonly string[] Names = ["Ready", "CredentialReady", "Uploaded", "Classified",
        "LayoutRead", "MetadataExtracted", "MetadataValidated", "Persisted", "Returned"];
}

public sealed class PermanentFailure(string code) : Exception(code)
{
    public string Code { get; } = code;
}

// These boundaries will gain real Azure implementations in later stages.
public interface IPipelineAdapter
{
    Task ExecuteAsync(int stage, Job job, Submission manifest, CancellationToken cancellation);
}
public interface IResultRepository
{
    void Put(string id, Result value);
    Result Get(string id);
}

public sealed record Settings(string Root, string PolicyPath, bool Once, bool StatusOnly,
    int PollMs, int RetryBaseMs, string? CrashAfterEffect, string? FailOnceStage, string? AlwaysFailStage,
    string ExecutionMode = "Simulated", int StopAfterStage = 8);
