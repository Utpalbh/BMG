from diagrams import Diagram, Cluster, Edge
# Azure
from diagrams.azure.storage import BlobStorage
from diagrams.azure.database import CosmosDb
from diagrams.azure.network import VirtualNetworkGateways
from diagrams.azure.security import KeyVaults
try:
    from diagrams.azure.ml import CognitiveServices, AzureOpenAI
except ImportError:
    CognitiveServices = None
    AzureOpenAI = None
# On-prem / generic
from diagrams.onprem.client import Users, Client
from diagrams.onprem.compute import Server
# Generic fallback icons
from diagrams.generic.storage import Storage
from diagrams.generic.compute import Rack

# ============================================================
# HELPER FACTORIES (fall back to a generic icon if the
# installed diagrams version doesn't expose the Azure icon)
# ============================================================
def cognitive_services(label):
    return CognitiveServices(label) if CognitiveServices else Rack(label)

def azure_openai(label):
    return AzureOpenAI(label) if AzureOpenAI else Rack(label)

graph_attr = {
    "fontsize": "20",
    "fontname": "Helvetica-Bold",
    "bgcolor": "white",
    "pad": "0.5",
    "splines": "spline",
    "nodesep": "0.6",
    "ranksep": "1.0",
    "dpi": "300",
}
node_attr = {
    "fontsize": "13",
    "fontname": "Helvetica-Bold",
}
edge_attr = {
    "fontsize": "11",
    "fontname": "Helvetica-Bold",
    "fontcolor": "black",
}

with Diagram(
    "",
    filename="bmg_mvp_detailed_flow",
    show=False,
    direction="LR",
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    lender = Users("Lender")

    with Cluster("On-Premises"):
        jetdocs = Client("JetDocs")
        temp_folder = Storage("Temp Folder")
        orchestrator = Server("Upload /\nOrchestration\nService")

    with Cluster("Hybrid Connectivity"):
        vpn = VirtualNetworkGateways("Site-to-Site VPN /\nExpressRoute")

    with Cluster("Azure"):
        keyvault = KeyVaults("Key Vault")
        blob = BlobStorage("Blob Storage")

        with Cluster("Document Intelligence"):
            classifier = cognitive_services("Custom\nClassification")
            read_layout = cognitive_services("Read / Layout")

        openai = azure_openai("Azure OpenAI")
        cosmos = CosmosDb("Cosmos DB")

    with Cluster("On-Premises (Downstream)"):
        loantrack = Server("LoanTrack")
        edm = Storage("EDM")
        existing_process = Client("Existing\nWorkflow\nContinues")

    # ------------------------------------------------------
    # Numbered, single end-to-end path
    # ------------------------------------------------------
    lender >> Edge(label="1. Upload documents") >> jetdocs
    jetdocs >> Edge(label="2. Save PDFs") >> temp_folder
    temp_folder >> Edge(label="3. Detect new submission") >> orchestrator

    orchestrator >> Edge(
        label="4. Fetch SP credentials", style="dashed", color="gray40"
    ) >> keyvault

    orchestrator >> Edge(label="5. AzCopy upload") >> vpn
    vpn >> Edge(label="Service Principal auth") >> blob

    blob >> Edge(label="6. Classify document type") >> classifier
    classifier >> Edge(label="7. Document type confirmed") >> read_layout
    read_layout >> Edge(label="8. OCR + layout data") >> openai
    openai >> Edge(label="9. Structured metadata JSON") >> cosmos

    cosmos >> Edge(label="10. Validated metadata\n(private link)") >> orchestrator

    orchestrator >> Edge(label="11. Create transaction") >> loantrack
    loantrack >> Edge(label="12. Invoice number") >> orchestrator
    orchestrator >> Edge(label="13. Upload documents + Invoice #") >> edm
    edm >> Edge(label="14. Existing workflow continues") >> existing_process
