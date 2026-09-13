using Microsoft.Data.Sqlite;

namespace Bmg.Intake;

public sealed class StateStore : IDisposable
{
    private readonly SqliteConnection connection;
    public StateStore(string path)
    {
        connection = new SqliteConnection(new SqliteConnectionStringBuilder
        { DataSource = path, Pooling = false, DefaultTimeout = 10 }.ToString());
        connection.Open();
        Execute("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, revision INTEGER NOT NULL,
              digest TEXT NOT NULL, snapshot TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'Pending', attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt_utc INTEGER NOT NULL DEFAULT 0, error_code TEXT,
              UNIQUE(submission_id, revision));
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, stage TEXT NOT NULL,
              outcome TEXT NOT NULL, timestamp_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intake_errors (
              folder_key TEXT PRIMARY KEY, code TEXT NOT NULL, timestamp_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_requests (
              request_key TEXT PRIMARY KEY, kind TEXT NOT NULL, pages INTEGER NOT NULL,
              status TEXT NOT NULL, operation TEXT, result_json TEXT);
            CREATE TABLE IF NOT EXISTS llm_usage (
              request_key TEXT PRIMARY KEY, input_reserved INTEGER NOT NULL, output_reserved INTEGER NOT NULL,
              input_actual INTEGER, output_actual INTEGER);
            """);
    }
    private void Execute(string sql, params (string, object?)[] parameters)
    {
        using var command = connection.CreateCommand(); command.CommandText = sql;
        foreach (var (name, value) in parameters) command.Parameters.AddWithValue(name, value ?? DBNull.Value);
        command.ExecuteNonQuery();
    }
    private static Job Read(SqliteDataReader r) => new(r.GetString(0), r.GetString(1), r.GetInt32(2),
        r.GetString(3), r.GetString(4), r.GetInt32(5), r.GetString(6), r.GetInt32(7), r.GetInt64(8),
        r.IsDBNull(9) ? null : r.GetString(9));
    public Job? Find(string submission, int revision)
    {
        using var c = connection.CreateCommand();
        c.CommandText = "SELECT * FROM jobs WHERE submission_id=$s AND revision=$r";
        c.Parameters.AddWithValue("$s", submission); c.Parameters.AddWithValue("$r", revision);
        using var reader = c.ExecuteReader(); return reader.Read() ? Read(reader) : null;
    }
    public List<Job> All()
    {
        using var c = connection.CreateCommand(); c.CommandText = "SELECT * FROM jobs ORDER BY rowid";
        using var r = c.ExecuteReader(); var jobs = new List<Job>();
        while (r.Read()) jobs.Add(Read(r)); return jobs;
    }
    public List<object> IntakeIssues()
    {
        using var c = connection.CreateCommand(); c.CommandText = "SELECT folder_key,code,timestamp_utc FROM intake_errors ORDER BY folder_key";
        using var r = c.ExecuteReader(); var issues = new List<object>();
        while (r.Read()) issues.Add(new { folderKey = r.GetString(0), code = r.GetString(1), timestampUtc = r.GetString(2) });
        return issues;
    }
    public void Add(Job job)
    {
        using var tx = connection.BeginTransaction();
        Execute("INSERT INTO jobs(id,submission_id,revision,digest,snapshot) VALUES($id,$s,$r,$d,$p)",
            ("$id", job.Id), ("$s", job.SubmissionId), ("$r", job.Revision), ("$d", job.Digest), ("$p", job.Snapshot));
        Event(job.Id, "Ready", "Checkpoint"); tx.Commit();
    }
    public void Checkpoint(Job job, int stage, string? checkpointStatus = null)
    {
        using var tx = connection.BeginTransaction();
        Execute("UPDATE jobs SET stage=$stage,status=$status,attempts=0,next_attempt_utc=0,error_code=NULL WHERE id=$id",
            ("$stage", stage), ("$status", checkpointStatus ?? (stage == Stages.Names.Length - 1 ? "Returned" : "Pending")), ("$id", job.Id));
        Event(job.Id, Stages.Names[stage], "Checkpoint"); tx.Commit();
    }
    public void Fail(Job job, string code, bool permanent, int retryBaseMs)
    {
        int attempt = job.Attempts + 1;
        string status = permanent ? "ManualException" : attempt >= 4 ? "RetryExhausted" : "RetryPending";
        long due = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() +
            (long)(retryBaseMs * Math.Pow(2, attempt - 1)) + Random.Shared.Next(1, 50);
        using var tx = connection.BeginTransaction();
        Execute("UPDATE jobs SET status=$s,attempts=$a,next_attempt_utc=$due,error_code=$c WHERE id=$id",
            ("$s", status), ("$a", attempt), ("$due", due), ("$c", code), ("$id", job.Id));
        Event(job.Id, Stages.Names[Math.Min(job.Stage + 1, Stages.Names.Length - 1)], status + ":" + code);
        tx.Commit();
    }
    public bool IntakeError(string folderKey, string code)
    {
        using var c = connection.CreateCommand();
        c.CommandText = "SELECT code FROM intake_errors WHERE folder_key=$f";
        c.Parameters.AddWithValue("$f", folderKey);
        if (c.ExecuteScalar() as string == code) return false;
        Execute("INSERT INTO intake_errors VALUES($f,$c,$t) ON CONFLICT(folder_key) DO UPDATE SET code=$c,timestamp_utc=$t",
            ("$f", folderKey), ("$c", code), ("$t", DateTimeOffset.UtcNow.ToString("O")));
        return true;
    }
    public void ClearIntakeError(string key) => Execute("DELETE FROM intake_errors WHERE folder_key=$f", ("$f", key));
    public (string Status, string? Operation, string? Result)? AiRequest(string key)
    {
        using var c = connection.CreateCommand(); c.CommandText = "SELECT status,operation,result_json FROM ai_requests WHERE request_key=$k";
        c.Parameters.AddWithValue("$k", key); using var r = c.ExecuteReader();
        return r.Read() ? (r.GetString(0), r.IsDBNull(1) ? null : r.GetString(1), r.IsDBNull(2) ? null : r.GetString(2)) : null;
    }
    public void ReserveAi(string key, string kind, int pages, int limit)
    {
        using var tx = connection.BeginTransaction();
        using var c = connection.CreateCommand(); c.CommandText = "SELECT COALESCE(SUM(pages),0) FROM ai_requests WHERE kind=$kind";
        c.Parameters.AddWithValue("$kind", kind);
        if (Convert.ToInt64(c.ExecuteScalar()) + pages > limit) throw new PermanentFailure("AiPageBudgetExceeded");
        Execute("INSERT INTO ai_requests(request_key,kind,pages,status) VALUES($k,$kind,$p,'Submitting')", ("$k",key),("$kind",kind),("$p",pages));
        tx.Commit();
    }
    public void UpdateAi(string key, string status, string? operation, string? result = null) => Execute(
        "UPDATE ai_requests SET status=$s,operation=$o,result_json=$r WHERE request_key=$k", ("$k",key),("$s",status),("$o",operation),("$r",result));
    public void ReserveLlm(string key, int input, int output, int inputLimit, int outputLimit)
    {
        using var tx = connection.BeginTransaction();
        using var c = connection.CreateCommand();
        c.CommandText = "SELECT COALESCE(SUM(COALESCE(input_actual,input_reserved)),0),COALESCE(SUM(COALESCE(output_actual,output_reserved)),0) FROM llm_usage";
        using (var r = c.ExecuteReader())
        {
            r.Read();
            if (r.GetInt64(0) + input > inputLimit || r.GetInt64(1) + output > outputLimit) throw new PermanentFailure("LlmTokenBudgetExceeded");
        }
        Execute("INSERT INTO llm_usage(request_key,input_reserved,output_reserved) VALUES($k,$i,$o)", ("$k",key),("$i",input),("$o",output));
        Execute("INSERT INTO ai_requests(request_key,kind,pages,status) VALUES($k,'llm',0,'Submitting')", ("$k",key));
        tx.Commit();
    }
    public void RecordLlmUsage(string key, int input, int output) => Execute("UPDATE llm_usage SET input_actual=$i,output_actual=$o WHERE request_key=$k", ("$k",key),("$i",input),("$o",output));
    public void Revalidate(Job job)
    {
        if (job.Stage != 5 || job.Status != "ManualException" || job.ErrorCode != "MetadataValidationFailed") throw new PermanentFailure("RevalidationNotEligible");
        using var tx = connection.BeginTransaction();
        Execute("UPDATE jobs SET status='Pending',attempts=0,next_attempt_utc=0,error_code=NULL WHERE id=$id", ("$id",job.Id));
        Event(job.Id,"MetadataValidated","ExplicitRevalidationOfCachedCandidates");tx.Commit();
    }
    private void Event(string id, string stage, string outcome) => Execute(
        "INSERT INTO events(job_id,stage,outcome,timestamp_utc) VALUES($id,$stage,$out,$t)",
        ("$id", id), ("$stage", stage), ("$out", outcome), ("$t", DateTimeOffset.UtcNow.ToString("O")));
    public void Dispose() => connection.Dispose();
}
