# AI_hedge_fund

                ┌──────────────────┐
                │ Financial APIs   │
                │ SEC Filings      │
                │ News APIs        │
                └────────┬─────────┘
                         │
                  Data Ingestion
                         │
                ┌────────▼─────────┐
                │ Cleaning/Chunking│
                └────────┬─────────┘
                         │
                   Embeddings
                         │
                ┌────────▼─────────┐
                │ Vector Database  │
                │ Chroma / FAISS   │
                └────────┬─────────┘
                         │
                    Retriever
                         │
               ┌─────────▼─────────┐
               │ LLM Reasoning     │
               │ Summaries         │
               │ Comparisons       │
               └─────────┬─────────┘
                         │
                  Streamlit UI