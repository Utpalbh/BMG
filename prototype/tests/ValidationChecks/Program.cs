using Bmg.Intake;
using System.Text.Json;
var validator = new MetadataValidator(args[0]);
var fields = new Dictionary<string,string> { ["lenderCode"]="0017",["loanNumber"]="00924",["borrowerName"]="Morgan Willow",["propertyAddress"]="100 Juniper Lane, Austin, TX 78701",["closingDate"]="September 18, 2026",["loanType"]="Conventional",["purpose"]="Purchase" };
var docs = new[]{new Document("doc-001","a.pdf","hash1"),new Document("doc-002","b.pdf","hash2")};
var manifest = new Submission("poc-1","test",1,"LocalStagingPoC","Examination",docs);
var classes = new[]{new ClassificationReceipt("doc-001","hash1","model","ClosingInstructions",.99,1,true),new ClassificationReceipt("doc-002","hash2","model","Note",.99,1,true)};
FieldCandidate[] Candidates() => docs.SelectMany(d => fields.Select(f => new FieldCandidate(d.DocumentId,f.Key,f.Value,1,f.Key+": "+f.Value))).ToArray();
OcrPage[] Pages(FieldCandidate[] c) => docs.Select(d=>new OcrPage(d.DocumentId,1,string.Join("\n",c.Where(x=>x.DocumentId==d.DocumentId).Select(x=>x.Quote)))).ToArray();
var report = new List<object>();
void Check(string name, Action action) { action();report.Add(new{name,passed=true}); }
Result Validate(FieldCandidate[] c,OcrPage[] p)=>validator.Validate(manifest,new(c),classes,p,"model","prompt");
void Reject(FieldCandidate[] c,OcrPage[] p,string code){if(!Validate(c,p).ValidationErrors.Any(x=>x.Contains(code)))throw new Exception(code);}
Check("valid_evidence_and_date_normalization",()=>{var c=Candidates();var r=Validate(c,Pages(c));if(r.Status!="Validated"||r.Metadata["closingDate"]!="2026-09-18"||r.Metadata["loanNumber"]!="00924")throw new Exception();});
Check("labelled_value_normalized_without_losing_evidence",()=>{var c=Candidates();var pages=Pages(c);c=c.Select(x=>x with{Value=x.Quote}).ToArray();var r=Validate(c,pages);if(r.Status!="Validated"||r.Metadata["loanNumber"]!="00924"||r.Metadata["closingDate"]!="2026-09-18")throw new Exception();});
Check("fabricated_quote_rejected",()=>{var c=Candidates();var p=Pages(c);c[0]=c[0] with{Quote="fabricated 0017"};Reject(c,p,"EvidenceMismatch");});
Check("wrong_page_rejected",()=>{var c=Candidates();var p=Pages(c);c[0]=c[0] with{Page=2};Reject(c,p,"EvidenceMismatch");});
Check("value_not_in_quote_rejected",()=>{var c=Candidates();var p=Pages(c);c[0]=c[0] with{Value="0018"};Reject(c,p,"EvidenceMismatch");});
Check("substring_identifier_rejected",()=>{var c=Candidates();var p=Pages(c);c[0]=c[0] with{Value="017"};Reject(c,p,"EvidenceMismatch");});
Check("conflict_not_hidden_by_source_priority",()=>{var c=Candidates();c[8]=c[8] with{Value="00925",Quote="loanNumber: 00925"};Reject(c,Pages(c),"Conflict");});
Check("missing_required_rejected",()=>{var c=Candidates().Select(x=>x.Field=="lenderCode"?x with{Value=null,Quote=null,Page=null}:x).ToArray();Reject(c,Pages(c),"Required");});
Check("ambiguous_date_rejected",()=>{var c=Candidates().Select(x=>x.Field=="closingDate"?x with{Value="09/10/2026",Quote="closingDate: 09/10/2026"}:x).ToArray();Reject(c,Pages(c),"AmbiguousOrInvalidDate");});
Check("missing_document_assessment_rejected",()=>{var c=Candidates();Reject(c.Skip(1).ToArray(),Pages(c),"AssessmentMissing");});
Check("unknown_document_rejected",()=>{var c=Candidates();c[0]=c[0] with{DocumentId="outside"};try{Validate(c,Pages(c));throw new Exception();}catch(PermanentFailure e)when(e.Code=="CandidateContractInvalid"){} });
Check("llm_budget_and_unknown_intent_durable",()=>{string p=Path.Combine(Path.GetTempPath(),"bmg-llm-test-"+Guid.NewGuid()+".db");using(var s=new StateStore(p)){s.ReserveLlm("one",90,90,100,100);try{s.ReserveLlm("two",20,20,100,100);throw new Exception();}catch(PermanentFailure e)when(e.Code=="LlmTokenBudgetExceeded"){} }using(var s=new StateStore(p)){if(s.AiRequest("one")?.Status!="Submitting"||s.AiRequest("two") is not null)throw new Exception();}});
File.WriteAllText(args[1],JsonSerializer.Serialize(new{passed=report.Count,failed=0,tests=report},Json.Options));Console.WriteLine($"PASS {report.Count} validation and durable budget checks");
