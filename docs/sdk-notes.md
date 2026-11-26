# SDK and format notes

Record every SDK assumption here: package, version, method, Learn page consulted, date.
**Verified** = confirmed in official documentation. **To verify** = check with one live call /
the official schema before relying on it.

## Formats
| Area | Detail | Status |
|---|---|---|
| FatturaPA | Namespace `http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2`, `FormatoTrasmissione=FPR12`. Fields used: CedentePrestatore/IdFiscaleIVA, Denominazione, DatiGeneraliDocumento (Divisa, Data, Numero, ImportoTotaleDocumento), DatiOrdineAcquisto/IdDocumento, DettaglioLinee, DatiRiepilogo, DettaglioPagamento (DataScadenzaPagamento, IBAN). | To verify: validate one generated sample against the official XSD |
| KSeF FA(3) | Structure per the Ministry of Finance information sheet on the FA(3) logical structure (Naglowek, Podmiot1/2, Fa, FaWiersz, Platnosc, WarunkiTransakcji), consulted 2026-11-18. FA(3) is the structure in force from February 2026. Field codes used: see `ingestion/ksef.py` docstring. Generator namespace `http://crd.gov.pl/wzor/2025/06/25/13775/`. | To verify: element codes (P_13_x/P_14_x slots, NrRB, Zamowienia/NrZamowienia) and namespace against the official XSD + sample XML |
| XML security | lxml `resolve_entities=False`, `no_network=True`, `load_dtd=False`; XXE test. | Verified by test |

## Azure SDKs (optional `azure` extra; mock mode never imports them)
| Package | Pinned | Usage | Status |
|---|---|---|---|
| `azure-ai-documentintelligence` | 1.0.2 | SDK 1.0.x ↔ service API `2024-11-30` (Learn README, consulted 2026-11-18). Entra ID auth needs a **single-service** Document Intelligence resource. | Verified (docs) |
| ″ | ″ | `begin_analyze_document("prebuilt-invoice", AnalyzeDocumentRequest(bytes_source=...), features=[DocumentAnalysisFeature.QUERY_FIELDS], query_fields=["PurchaseOrderNumber","IBAN"])` then `.result().as_dict()` | **To verify** with one live call (`make record`) — isolated in `adapters/document_intelligence.py::_analyze` |
| ″ | ″ | prebuilt-invoice field names in `ingestion/di_mapping.py::FIELD_MAP` (VendorTaxId, InvoiceId, InvoiceDate, DueDate, PurchaseOrder, SubTotal, TotalTax, InvoiceTotal, Items[ProductCode, Description, Quantity, UnitPrice, Amount, TaxRate], PaymentDetails[IBAN]) | **To verify** against the prebuilt-invoice field list for API 2024-11-30 |
| `openai` | 1.109.1 | Microsoft Learn "structured outputs" sample: `OpenAI(base_url="<endpoint>/openai/v1/", api_key=get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default"))`, `client.beta.chat.completions.parse(model=<deployment>, response_format=<Pydantic>)` (consulted 2026-11-18). | Verified (docs). **To verify:** pinned version supports a callable `api_key` |
| `azure-identity` | 1.25.0 | `DefaultAzureCredential`, `get_bearer_token_provider` | To verify pinned version, bump if needed |

## Tooling
| Package | Pinned | Notes |
|---|---|---|
| SQLAlchemy / Alembic / psycopg | 2.0.36 / 1.14.0 / 3.2.3 | Known releases; bump deliberately |
| reportlab / Pillow | 4.4.6 / 12.3.0 | `Canvas(invariant=1)` for reproducible PDFs; `ImageFont.load_default(size=...)` |
| Streamlit | 1.66.1 | `st.cache_resource`, `AppTest` |

## Open questions for v2
- Foundry Agent Service: which API generation / SDK package; whether structured outputs are
  supported with agents (an Azure Developer Learn article lists Agents as unsupported).
