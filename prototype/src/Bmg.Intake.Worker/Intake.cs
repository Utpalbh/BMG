using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Bmg.Intake;

public static partial class Intake
{
    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
    private static partial Regex Identifier();
    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._ -]{0,150}\\.pdf$")]
    private static partial Regex PdfName();
    [GeneratedRegex("^[a-f0-9]{64}$")]
    private static partial Regex HashPattern();
    public static string Hash(byte[] data) => Convert.ToHexStringLower(SHA256.HashData(data));
    public static string FolderKey(string folder) => Hash(Encoding.UTF8.GetBytes(Path.GetFullPath(folder)));
    public static void NoLink(string path)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new PermanentFailure("ReparsePointRejected");
    }
    public static byte[] ReadLocked(string path, int maximumBytes)
    {
        NoLink(path);
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (input.Length > maximumBytes) throw new PermanentFailure("FileSizeLimit");
        using var buffer = new MemoryStream(); input.CopyTo(buffer); return buffer.ToArray();
    }
    private static void RejectDuplicateProperties(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in element.EnumerateObject())
            {
                if (!names.Add(p.Name)) throw new PermanentFailure("DuplicateJsonProperty");
                RejectDuplicateProperties(p.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
            foreach (var item in element.EnumerateArray()) RejectDuplicateProperties(item);
    }
    public static Job? Capture(string folder, string root, StateStore store)
    {
        NoLink(folder); NoLink(Path.Combine(folder, "_READY"));
        byte[] manifestBytes = ReadLocked(Path.Combine(folder, "submission.json"), 1_048_576);
        // Windows PowerShell 5's UTF8 writer adds a BOM; accept that encoding safely.
        if (manifestBytes.Length >= 3 && manifestBytes[0] == 0xef && manifestBytes[1] == 0xbb && manifestBytes[2] == 0xbf)
            manifestBytes = manifestBytes[3..];
        using (var parsed = JsonDocument.Parse(manifestBytes)) RejectDuplicateProperties(parsed.RootElement);
        var m = JsonSerializer.Deserialize<Submission>(manifestBytes, Json.Options)
            ?? throw new PermanentFailure("InvalidManifest");
        if (m.SchemaVersion != "poc-1" || m.Source != "LocalStagingPoC" || m.SubmissionType != "Examination"
            || m.SubmissionId is null || !Identifier().IsMatch(m.SubmissionId) || m.Revision < 1
            || m.Documents is null || m.Documents.Length is < 1 or > 30)
            throw new PermanentFailure("InvalidManifest");
        var ids = new HashSet<string>(StringComparer.Ordinal);
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "submission.json", "_READY" };
        foreach (var d in m.Documents)
        {
            if (d is null || d.DocumentId is null || !Identifier().IsMatch(d.DocumentId)
                || d.FileName is null || !PdfName().IsMatch(d.FileName)
                || d.Sha256 is null || !HashPattern().IsMatch(d.Sha256)
                || !ids.Add(d.DocumentId) || !names.Add(d.FileName))
                throw new PermanentFailure("InvalidDocumentEntry");
        }
        foreach (var item in Directory.EnumerateFileSystemEntries(folder))
            if (!names.Contains(Path.GetFileName(item))) throw new PermanentFailure("UnexpectedStagingFile");
        // Keep verified bytes in memory while making a snapshot, eliminating a re-open race.
        long total = 0; var documents = new Dictionary<string, byte[]>();
        foreach (var d in m.Documents)
        {
            string path = Path.GetFullPath(Path.Combine(folder, d.FileName));
            if (!path.StartsWith(Path.GetFullPath(folder) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new PermanentFailure("PathTraversal");
            byte[] content = ReadLocked(path, 50 * 1024 * 1024); total += content.Length;
            if (total > 200 * 1024 * 1024) throw new PermanentFailure("SubmissionSizeLimit");
            if (content.Length < 8 || !content.AsSpan(0, 5).SequenceEqual("%PDF-"u8))
                throw new PermanentFailure("InvalidPdfSignature");
            if (Hash(content) != d.Sha256) throw new PermanentFailure("HashMismatch");
            documents.Add(d.FileName, content);
        }
        var canonical = m with { Documents = m.Documents.OrderBy(d => d.DocumentId, StringComparer.Ordinal).ToArray() };
        string digest = Hash(JsonSerializer.SerializeToUtf8Bytes(canonical, Json.Options));
        Job? previous = store.Find(m.SubmissionId, m.Revision);
        if (previous is not null)
        {
            if (previous.Digest != digest) throw new PermanentFailure("RevisionContentConflict");
            return null;
        }
        string snapshot = Path.Combine(root, "snapshots", digest);
        if (!Directory.Exists(snapshot))
        {
            string pending = snapshot + "." + Guid.NewGuid().ToString("N") + ".incoming";
            Directory.CreateDirectory(pending);
            foreach (var (name, bytes) in documents)
            {
                using var file = new FileStream(Path.Combine(pending, name), FileMode.CreateNew, FileAccess.Write, FileShare.None);
                file.Write(bytes); file.Flush(true);
            }
            Json.Write(Path.Combine(pending, "submission.json"), canonical);
            Directory.Move(pending, snapshot);
        }
        // A crash between snapshot rename and database insertion is safe to replay.
        VerifySnapshot(snapshot, canonical);
        var job = new Job(digest, m.SubmissionId, m.Revision, digest, snapshot, 0, "Pending", 0, 0, null);
        store.Add(job); return job;
    }
    public static void VerifySnapshot(string snapshot, Submission manifest)
    {
        NoLink(snapshot);
        foreach (var d in manifest.Documents)
            if (Hash(ReadLocked(Path.Combine(snapshot, d.FileName), 50 * 1024 * 1024)) != d.Sha256)
                throw new PermanentFailure("SnapshotIntegrityFailure");
    }
}
