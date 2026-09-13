# BM&G MVP Synthetic Test Data

This dataset is entirely synthetic and is intended only for the BM&G MVP proof of concept.

- 5 synthetic submissions
- 6 candidate mortgage document classes per submission
- 30 one-page PDF documents total
- Each class has 5 samples, which satisfies the Azure Document Intelligence custom-classifier minimum sample count for a PoC training set.
- `expected-invoice-metadata.json` contains a placeholder invoice metadata contract. It is **not** a confirmed BM&G production schema.

Treat each `submission-XXX` directory as one JetDocs intake unit for the file-system-trigger PoC.
