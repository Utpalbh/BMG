using System.Text.Json;

namespace Bmg.Intake;

public sealed class Worker(Settings settings, StateStore store, IPipelineAdapter adapter)
{
    public void Log(string stage, string outcome, string? id = null)
    {
        string entry = JsonSerializer.Serialize(new { timestampUtc = DateTimeOffset.UtcNow, executionMode = settings.ExecutionMode, jobId = id, stage, outcome });
        Console.WriteLine(entry);
        File.AppendAllText(Path.Combine(settings.Root, "logs", "worker.jsonl"), entry + Environment.NewLine);
    }
    public async Task Iteration(CancellationToken cancellation)
    {
        foreach (string folder in Directory.EnumerateDirectories(Path.Combine(settings.Root, "staging")))
        {
            cancellation.ThrowIfCancellationRequested();
            string key = Intake.FolderKey(folder);
            try
            {
                Intake.NoLink(folder);
                if (!File.Exists(Path.Combine(folder, "_READY"))) continue;
                Job? captured = Intake.Capture(folder, settings.Root, store);
                store.ClearIntakeError(key);
                string receipt = Path.Combine(settings.Root, "exceptions", "intake-" + key + ".json");
                if (File.Exists(receipt)) File.Delete(receipt);
                if (captured is not null) Log("Ready", "Captured", captured.Id);
            }
            catch (Exception e) when (e is PermanentFailure or JsonException or IOException or UnauthorizedAccessException)
            {
                string code = e is PermanentFailure permanent ? permanent.Code : e is JsonException ? "InvalidManifestJson" : "IntakeFileNotReady";
                if (store.IntakeError(key, code))
                {
                    Json.Write(Path.Combine(settings.Root, "exceptions", "intake-" + key + ".json"),
                        new { executionMode = settings.ExecutionMode, folderKey = key, code, action = "Repair the ready submission or stage an explicit new revision. Original files were retained." });
                    Log("Intake", code, key);
                }
            }
        }
        foreach (Job queued in store.All().Where(j => j.Status is "Pending" or "RetryPending" or "Uploaded" && j.Stage < settings.StopAfterStage && j.NextAttemptUtc <= DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()))
        {
            Job job = queued;
            try
            {
                var m = Json.Read<Submission>(Path.Combine(job.Snapshot, "submission.json"));
                if (Intake.Hash(JsonSerializer.SerializeToUtf8Bytes(m, Json.Options)) != job.Digest)
                    throw new PermanentFailure("SnapshotManifestChanged");
                Intake.VerifySnapshot(job.Snapshot, m);
                for (int stage = job.Stage + 1; stage <= settings.StopAfterStage; stage++)
                {
                    cancellation.ThrowIfCancellationRequested();
                    await adapter.ExecuteAsync(stage, job, m, cancellation);
                    if (settings.CrashAfterEffect == Stages.Names[stage])
                    {
                        Log(Stages.Names[stage], "SimulatedProcessCrashBeforeCheckpoint", job.Id);
                        Environment.Exit(75);
                    }
                    store.Checkpoint(job, stage, stage == settings.StopAfterStage ? Stages.Names[stage] : null);
                    Log(Stages.Names[stage], "Checkpoint", job.Id);
                    job = job with { Stage = stage, Attempts = 0, Status = "Pending", NextAttemptUtc = 0 };
                }
            }
            catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
            catch (Exception e) when (e is PermanentFailure or IOException or UnauthorizedAccessException or JsonException)
            {
                bool permanent = e is PermanentFailure or JsonException or UnauthorizedAccessException;
                string code = e is PermanentFailure failure ? failure.Code : e is JsonException ? "StoredArtifactInvalid" : e is UnauthorizedAccessException ? "LocalAccessDenied" : "TransientIoFailure";
                store.Fail(job, code, permanent, settings.RetryBaseMs);
                var after = store.Find(job.SubmissionId, job.Revision)!;
                Json.Write(Path.Combine(settings.Root, "exceptions", job.Id + ".json"),
                    new { executionMode = settings.ExecutionMode, job.SubmissionId, job.Revision, code, after.Status, after.Attempts, lastCheckpoint = Stages.Names[job.Stage] });
                Log(Stages.Names[job.Stage], after.Status + ":" + code, job.Id);
            }
            if (store.Find(job.SubmissionId, job.Revision)?.Status is "Returned" or "Uploaded" or "LayoutRead")
            {
                string receipt = Path.Combine(settings.Root, "exceptions", job.Id + ".json");
                if (File.Exists(receipt)) File.Delete(receipt);
            }
        }
    }
}
