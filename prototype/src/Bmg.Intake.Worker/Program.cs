using System.Text.Json;
using System.Threading.Channels;
using Bmg.Intake;

try
{
    var flags = new HashSet<string>(); var values = new Dictionary<string, string>();
    string[] flagNames = ["--simulate", "--azure-upload", "--azure-documents", "--azure-full", "--verify-identity", "--once", "--status", "--help"];
    string[] valueNames = ["--revalidate", "--root", "--policy", "--azure-config", "--poll-ms", "--retry-base-ms", "--crash-after-effect", "--fail-once-stage", "--always-fail-stage"];
    for (int i = 0; i < args.Length; i++)
    {
        if (flagNames.Contains(args[i])) { if (!flags.Add(args[i])) throw new ArgumentException("Duplicate option."); }
        else if (valueNames.Contains(args[i]) && i + 1 < args.Length) values.Add(args[i], args[++i]);
        else throw new ArgumentException("Unknown or incomplete option.");
    }
    if (flags.Contains("--help"))
    {
        Console.WriteLine("BMG: (--simulate | --azure-upload --azure-config PATH | --azure-documents --azure-config PATH | --azure-full --azure-config PATH) [--root PATH] [--once | --status]\nAzure upload stops at Uploaded; Azure documents stops at LayoutRead. Full mode continues through LLM, validation, Cosmos and local return. --verify-identity checks upload identity scope.\nTest-only fault options: --crash-after-effect STAGE, --fail-once-stage STAGE, --always-fail-stage STAGE");
        return 0;
    }
    bool full = flags.Contains("--azure-full");
    bool documents = flags.Contains("--azure-documents") || full;
    bool azure = flags.Contains("--azure-upload") || documents;
    if (new[] { "--simulate", "--azure-upload", "--azure-documents", "--azure-full" }.Count(flags.Contains) != 1) throw new ArgumentException("Select exactly one execution mode: --simulate, --azure-upload, --azure-documents, or --azure-full.");
    if (azure && (!values.ContainsKey("--azure-config") || !values.ContainsKey("--root"))) throw new ArgumentException("Azure mode requires --azure-config and an isolated --root.");
    if (!azure && (values.ContainsKey("--azure-config") || flags.Contains("--verify-identity"))) throw new ArgumentException("Azure options cannot be used in simulation mode.");
    if (azure && (values.ContainsKey("--fail-once-stage") || values.ContainsKey("--always-fail-stage"))) throw new ArgumentException("Synthetic failure injection is simulation-only.");
    string root = Path.GetFullPath(values.GetValueOrDefault("--root", Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Documents", "BmgPocRuntime")));
    string? oneDrive = Environment.GetEnvironmentVariable("OneDrive");
    if (!string.IsNullOrEmpty(oneDrive) && (root.Equals(Path.GetFullPath(oneDrive), StringComparison.OrdinalIgnoreCase)
        || root.StartsWith(Path.GetFullPath(oneDrive) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
        throw new ArgumentException("Use a runtime root outside OneDrive.");
    int pollMs = int.Parse(values.GetValueOrDefault("--poll-ms", "10000"));
    int retryMs = int.Parse(values.GetValueOrDefault("--retry-base-ms", "1000"));
    if (pollMs is < 50 or > 60000 || retryMs is < 50 or > 60000) throw new ArgumentException("Polling and retry intervals must be between 50 and 60000 ms.");
    foreach (string option in new[] { "--crash-after-effect", "--fail-once-stage", "--always-fail-stage" })
        if (values.TryGetValue(option, out var stage) && !Stages.Names.Skip(1).Contains(stage)) throw new ArgumentException("Unknown fault stage.");
    foreach (string dir in new[] { "", "staging", "state", "logs", "snapshots", "results", "exceptions", "completed", "fixtures", "simulated-blob", "simulated-cosmos" })
    { string path = Path.Combine(root, dir); Directory.CreateDirectory(path); Intake.NoLink(path); }
    var settings = new Settings(root, Path.GetFullPath(values.GetValueOrDefault("--policy", Path.Combine(AppContext.BaseDirectory, "metadata-policy.json"))),
        flags.Contains("--once"), flags.Contains("--status"), pollMs, retryMs,
        values.GetValueOrDefault("--crash-after-effect"), values.GetValueOrDefault("--fail-once-stage"), values.GetValueOrDefault("--always-fail-stage"), full ? "AzureFull" : documents ? "AzureDocuments" : azure ? "AzureUpload" : "Simulated", full ? 8 : documents ? 4 : azure ? 2 : 8);
    AzureFullConfiguration? fullConfiguration = full ? Json.Read<AzureFullConfiguration>(values["--azure-config"]) : null;
    AzureDocumentConfiguration? documentConfiguration = full ? fullConfiguration!.Documents : documents ? Json.Read<AzureDocumentConfiguration>(values["--azure-config"]) : null;
    AzureUploadConfiguration? azureConfiguration = documents ? documentConfiguration!.Upload : azure ? Json.Read<AzureUploadConfiguration>(values["--azure-config"]) : null;
    string binding = full ? fullConfiguration!.RuntimeBinding(settings.PolicyPath) : documents ? documentConfiguration!.RuntimeBinding() : azure ? azureConfiguration!.RuntimeBinding() : "Simulated";
    string modeFile = Path.Combine(root, "state", "execution-mode.txt");
    if (File.Exists(modeFile) && File.ReadAllText(modeFile) != binding) throw new ArgumentException("Runtime is bound to another execution mode or Azure destination/identity.");
    if (azure && !File.Exists(modeFile) && File.Exists(Path.Combine(root, "state", "intake.db"))) throw new ArgumentException("Azure mode requires a new or already bound Azure runtime.");
    if (settings.StatusOnly)
    {
        if (!File.Exists(Path.Combine(root, "state", "intake.db")))
        {
            Console.WriteLine(JsonSerializer.Serialize(new { executionMode = settings.ExecutionMode, jobs = Array.Empty<Job>(), intakeIssues = Array.Empty<object>() }, Json.Options));
            return 0;
        }
        using var statusStore = new StateStore(Path.Combine(root, "state", "intake.db"));
        Console.WriteLine(JsonSerializer.Serialize(new { executionMode = settings.ExecutionMode, jobs = statusStore.All(), intakeIssues = statusStore.IntakeIssues() }, Json.Options));
        return 0;
    }
    // FileShare.None provides a process-wide ownership lock, released by the OS even after a crash.
    using var processLock = new FileStream(Path.Combine(root, "state", "worker.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
    if (!File.Exists(modeFile)) File.WriteAllText(modeFile, binding);
    using var store = new StateStore(Path.Combine(root, "state", "intake.db"));
    if (values.TryGetValue("--revalidate", out var revalidateId))
    {
        if (!full || !settings.Once) throw new ArgumentException("Revalidation requires --azure-full --once.");
        var target = store.All().SingleOrDefault(j => j.Id == revalidateId) ?? throw new ArgumentException("Unknown job.");
        if (target.Stage != 5 || target.ErrorCode != "MetadataValidationFailed" || target.Status != "ManualException") throw new ArgumentException("Only a metadata validation failure can be revalidated.");
        _ = Json.Read<CandidateResponse>(Path.Combine(target.Snapshot, "candidates.json"));
        string prior = Path.Combine(target.Snapshot, "result.json");
        if (File.Exists(prior)) File.Copy(prior, Path.Combine(target.Snapshot, "result-before-revalidation-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssfff") + ".json"));
        store.Revalidate(target);
    }
    using var azureAdapter = azure ? new AzureUploadPipeline(settings, azureConfiguration!) : null;
    using var documentAdapter = documents ? new AzureDocumentPipeline(settings, documentConfiguration!, azureAdapter!, store) : null;
    if (flags.Contains("--verify-identity"))
    {
        bool passed = await azureAdapter!.VerifyIdentityAsync(CancellationToken.None);
        if (documentAdapter is not null) passed = await documentAdapter.VerifyIdentityAsync(CancellationToken.None) && passed;
        return passed ? 0 : 2;
    }
    IPipelineAdapter adapter = azureAdapter is null ? new SimulatedPipeline(settings, new FileResultRepository(root)) : azureAdapter;
    if (documentAdapter is not null) adapter = documentAdapter;
    using var fullAdapter = full ? new AzureFullPipeline(settings, fullConfiguration!, documentAdapter!, azureAdapter!, store) : null;
    if (fullAdapter is not null) adapter = fullAdapter;
    var worker = new Worker(settings, store, adapter);
    using var cancellation = new CancellationTokenSource();
    Console.CancelKeyPress += (_, e) => { e.Cancel = true; cancellation.Cancel(); };
    var wakeups = Channel.CreateBounded<bool>(new BoundedChannelOptions(1) { FullMode = BoundedChannelFullMode.DropWrite });
    using var watcher = new FileSystemWatcher(Path.Combine(root, "staging")) { IncludeSubdirectories = true, NotifyFilter = NotifyFilters.FileName | NotifyFilters.DirectoryName | NotifyFilters.LastWrite };
    watcher.Created += (_, _) => wakeups.Writer.TryWrite(true);
    watcher.Changed += (_, _) => wakeups.Writer.TryWrite(true);
    watcher.Renamed += (_, _) => wakeups.Writer.TryWrite(true);
    watcher.Error += (_, _) => wakeups.Writer.TryWrite(true); // Reconciliation recovers overflow.
    watcher.EnableRaisingEvents = true;
    worker.Log("Worker", full ? "Started:AZURE_FULL_FLOW" : documents ? "Started:AZURE_CLASSIFICATION_AND_OCR" : azure ? "Started:AZURE_UPLOAD_ONLY" : "Started:SIMULATED_SERVICES_ONLY");
    try
    {
        do
        {
            await worker.Iteration(cancellation.Token);
            if (settings.Once) break;
            using var wait = CancellationTokenSource.CreateLinkedTokenSource(cancellation.Token);
            wait.CancelAfter(settings.PollMs);
            try { await wakeups.Reader.ReadAsync(wait.Token); }
            catch (OperationCanceledException) when (!cancellation.IsCancellationRequested) { }
            while (wakeups.Reader.TryRead(out _)) { }
        } while (!cancellation.IsCancellationRequested);
    }
    catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { }
    worker.Log("Worker", "Stopped");
    return store.All().Any(j => j.Status != Stages.Names[settings.StopAfterStage]) || store.IntakeIssues().Count > 0 ? 2 : 0;
}
catch (IOException) { Console.Error.WriteLine("Worker could not acquire its runtime files. Another worker may own this runtime root, or local I/O failed."); return 3; }
catch (Exception e) { Console.Error.WriteLine("Worker configuration/startup failed: " + e.GetType().Name + (e is ArgumentException ? ": " + e.Message : "")); return 1; }



