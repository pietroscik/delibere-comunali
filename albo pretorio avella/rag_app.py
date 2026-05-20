import streamlit as st
import json
import os
import hashlib
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

# Langchain imports
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:
    try:
        from langchain_community.embeddings import HuggingFaceEmbeddings
    except ImportError:
        HuggingFaceEmbeddings = None

try:
    from langchain_community.chat_models import ChatOllama
except ImportError:
    ChatOllama = None

st.set_page_config(page_title="RAG Motore di Ricerca Albo", layout="wide", page_icon="🤖")

st.title("🤖 Motore di Ricerca RAG - Albo Pretorio")
st.markdown("Fai domande sui documenti dell'albo pretorio. L'AI cercherà le informazioni rilevanti e ti risponderà citando le fonti.")

# Carica automaticamente eventuali variabili da file .env
load_dotenv(override=True)

DEFAULT_EMBEDDING_MODELS = [
    os.environ.get("GOOGLE_EMBEDDING_MODEL", "").strip(),
    "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "text-embedding-004",
    "gemini-embedding-001",
]

DEFAULT_LLM_MODELS = [
    os.environ.get("GOOGLE_LLM_MODEL", "").strip(),
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
]

MODEL_PROFILES = {
    "Locale (Zero Quota API)": {
        "embedding_models": [
            "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ],
        "llm_models": [
            "ollama:llama3.1",
            "ollama:llama3",
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
        ],
        "embed_batch_size": 500,
        "embed_pause_sec": 0.0,
    },
    "Conservativo (meno quota)": {
        "embedding_models": [
            "text-embedding-004",
            "gemini-embedding-001",
            "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ],
        "llm_models": [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
        ],
        "embed_batch_size": 30,
        "embed_pause_sec": 62.0,
    },
    "Bilanciato": {
        "embedding_models": [
            "text-embedding-004",
            "gemini-embedding-001",
            "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ],
        "llm_models": [
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-1.5-flash",
        ],
        "embed_batch_size": 35,
        "embed_pause_sec": 60.0,
    },
    "Prestazioni (piu' veloce)": {
        "embedding_models": [
            "text-embedding-004",
            "gemini-embedding-001",
            "local:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ],
        "llm_models": [
            "gemini-2.5-flash",
            "gemini-1.5-flash",
            "gemini-3.1-flash-lite",
        ],
        "embed_batch_size": 40,
        "embed_pause_sec": 60.0,
    },
}

USE_GEMINI_DEFAULT = os.environ.get("RAG_USE_GEMINI_BY_DEFAULT", "").strip().lower() in {
    "1", "true", "yes", "on"
}
USE_LOCAL_RETRIEVER_WITH_GEMINI_DEFAULT = (
    os.environ.get("RAG_USE_LOCAL_RETRIEVER_WITH_GEMINI", "").strip().lower()
    in {"1", "true", "yes", "on"}
)

PROMPT_TEMPLATE = """Sei un assistente per l'analisi di atti amministrativi comunali. Usa i seguenti frammenti di testo estratti dai documenti per rispondere alla domanda.
Se non conosci la risposta in base al contesto, dì semplicemente che le informazioni non sono presenti nei documenti.
Cita sempre il nome del documento [Fonte: nome_file.pdf] da cui hai preso le informazioni alla fine della tua risposta.
Se pertinenti e disponibili nel contesto, includi anche i codici CIG e CUP.

Contesto:
{context}

Domanda: {question}

Risposta:"""


def _split_env_list(raw: str):
    if not raw:
        return []
    return [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]


def _unique_non_empty(items):
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_index_manifest(index_dir: Path, embedding_model: Optional[str] = None) -> dict:
    files = []
    for fp in sorted(index_dir.glob("*")):
        if fp.is_file():
            files.append({
                "name": fp.name,
                "size": fp.stat().st_size,
                "sha256": _sha256_file(fp),
            })
    return {
        "files": files,
        "embedding_model": embedding_model,
    }


def _index_is_trusted(index_dir: Path, manifest_path: Path, embedding_model: str) -> bool:
    if not index_dir.exists() or not manifest_path.exists():
        return False
    try:
        expected = json.loads(manifest_path.read_text(encoding="utf-8"))
        if expected.get("embedding_model") != embedding_model:
            return False
        current = _build_index_manifest(index_dir, embedding_model=embedding_model)
    except Exception:
        return False
    return expected == current


def _instantiate_embeddings_candidates(candidates):
    ready = []
    errors = []
    for model_name in _unique_non_empty(candidates):
        if model_name.startswith("local:"):
            if HuggingFaceEmbeddings is None:
                errors.append((model_name, "Modulo mancante. Esegui: pip install sentence-transformers langchain-huggingface"))
                continue
            try:
                local_model = model_name.split("local:", 1)[1]
                ready.append((model_name, HuggingFaceEmbeddings(model_name=local_model)))
            except Exception as exc:
                errors.append((model_name, str(exc)))
        else:
            try:
                # max_retries=0 velocizza il failover sul modello di embedding successivo in caso di quota esaurita
                ready.append((model_name, GoogleGenerativeAIEmbeddings(model=model_name, max_retries=0)))
            except Exception as exc:
                errors.append((model_name, str(exc)))
    return ready, errors


def _load_corpus_documents(corpus_path: Path):
    documents = []
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,
        chunk_overlap=300,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            text_content = data.get("text", "")
            if not text_content or len(text_content) < 50:
                continue

            metadata = {
                "pdf_name": data.get("pdf_name", "Sconosciuto"),
                "oggetto": data.get("oggetto", "N/D"),
                "cig": data.get("cig"),
                "cup": data.get("cup"),
            }

            # Prepariamo un prefisso con i metadati chiave per arricchire ogni chunk.
            # Questo migliora drasticamente l'accuratezza del retrieval e il contesto per l'LLM.
            prefix_parts = []
            if metadata["oggetto"] and metadata["oggetto"] != "N/D":
                # Puliamo e tronchiamo l'oggetto per non appesantire troppo
                clean_oggetto = " ".join(str(metadata['oggetto']).split())[:250]
                prefix_parts.append(f"Oggetto: {clean_oggetto}")
            if metadata["cig"]:
                prefix_parts.append(f"CIG: {metadata['cig']}")
            if metadata["cup"]:
                prefix_parts.append(f"CUP: {metadata['cup']}")
            prefix = ". ".join(prefix_parts)
            if prefix:
                prefix += ".\n\n"

            chunks = text_splitter.split_text(text_content)
            for chunk in chunks:
                # Aggiungiamo il prefisso a ogni frammento
                enriched_content = prefix + chunk
                documents.append(Document(page_content=enriched_content, metadata=metadata))
    return documents


def _tokenize(text: str):
    return re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+", (text or "").lower())


class LocalSearchChain:
    """Fallback locale senza API: ranking lessicale + snippet con fonti."""
    def __init__(self, documents, top_k=6):
        self.top_k = top_k
        self.retriever = LocalTokenRetriever(documents, top_k=top_k)

    def invoke(self, question: str) -> str:
        top_docs = self.retriever.invoke(question)

        if not top_docs:
            return (
                "Modalita' fallback locale attiva: "
                "nessun frammento rilevante trovato."
            )

        lines = [
            "⚠️ **Attenzione: L'Intelligenza Artificiale (Gemini) non è attiva.**",
            "Il sistema sta funzionando come un semplice motore di ricerca testuale. Per ottenere risposte ragionate dall'AI, inserisci la tua `GOOGLE_API_KEY` nel file `.env` e attiva Gemini dal menu laterale.",
            "",
            "**Ecco i documenti che contengono le parole cercate:**",
        ]
        for i, doc in enumerate(top_docs, 1):
            metadata = doc.metadata
            content = doc.page_content
            snippet = " ".join(content.split())[:320]
            source = metadata.get("pdf_name", "Sconosciuto")
            cig = metadata.get("cig")
            cup = metadata.get("cup")
            
            meta_str = f"[Fonte: {source}]"
            if cig: meta_str += f" [CIG: {cig}]"
            if cup: meta_str += f" [CUP: {cup}]"
            
            lines.append(f"{i}. {meta_str}\n   {snippet}...")
        return "\n\n".join(lines)


class LocalTokenRetriever:
    """Retriever lessicale locale compatibile con interfaccia retriever.invoke()."""

    def __init__(self, documents, top_k=6):
        self.top_k = top_k
        self.rows = []
        for doc in documents:
            tokens = set(_tokenize(doc.page_content))
            self.rows.append((tokens, doc))

    def invoke(self, question: str):
        q_tokens = set(_tokenize(question))
        if not q_tokens:
            return []

        scored = []
        for tokens, doc in self.rows:
            overlap = len(tokens & q_tokens)
            if overlap:
                scored.append((overlap, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[: self.top_k]]


class LLMFailoverRAGChain:
    def __init__(self, retriever, prompt_template: str, llm_models):
        self.retriever = retriever
        self.prompt = PromptTemplate.from_template(prompt_template)
        self.llm_candidates = []
        self.last_model = None
        self.cooldowns = {}
        errs = []
        for model_name in _unique_non_empty(llm_models):
            try:
                if model_name.startswith("ollama:"):
                    if ChatOllama is None:
                        errs.append((model_name, "Libreria mancante per Ollama"))
                        continue
                    local_model = model_name.split("ollama:", 1)[1]
                    llm = ChatOllama(model=local_model, temperature=0.1)
                    self.llm_candidates.append((model_name, llm))
                else:
                    # max_retries=0 disabilita il retry interno per far scattare subito il nostro failover
                    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.1, max_retries=0)
                    self.llm_candidates.append((model_name, llm))
            except Exception as exc:
                errs.append((model_name, str(exc)))

        if not self.llm_candidates:
            details = "\n".join([f"- {m}: {e}" for m, e in errs]) or "- nessun dettaglio"
            raise RuntimeError(
                "Nessun modello LLM Gemini inizializzabile. Imposta GOOGLE_LLM_MODEL_PRIORITY o GOOGLE_LLM_MODEL.\n"
                f"Tentativi:\n{details}"
            )

    def _format_docs(self, docs):
        formatted = []
        for d in docs:
            source = d.metadata.get('pdf_name', 'Sconosciuto')
            cig = d.metadata.get('cig')
            cup = d.metadata.get('cup')
            
            meta_str = f"[Fonte: {source}]"
            if cig: meta_str += f" [CIG: {cig}]"
            if cup: meta_str += f" [CUP: {cup}]"
                
            formatted.append(f"{meta_str}\nTesto: {d.page_content}")
        return "\n\n".join(formatted)

    def invoke(self, question: str) -> str:
        docs = self.retriever.invoke(question)
        context = self._format_docs(docs)
        prompt_value = self.prompt.format(context=context, question=question)

        errors = []
        now = time.time()
        tried_any = False
        for model_name, llm in self.llm_candidates:
            cooldown_until = self.cooldowns.get(model_name, 0.0)
            if cooldown_until > now:
                continue
            tried_any = True
            try:
                answer = llm.invoke(prompt_value)
                self.last_model = model_name
                if hasattr(answer, "content"):
                    return answer.content
                return str(answer)
            except Exception as exc:
                msg = str(exc)
                # Check più permissivo per intercettare ogni tipo di messaggio di esaurimento quota
                if "429" in msg or "exhausted" in msg.lower() or "quota" in msg.lower() or "rate" in msg.lower():
                    # Evita di riprovare subito il modello saturo per 60 secondi.
                    self.cooldowns[model_name] = time.time() + 60.0
                    st.toast(f"⚠️ Quota esaurita per `{model_name}`. Cambio modello in corso...", icon="🔄")
                errors.append((model_name, msg))

        if not tried_any:
            raise RuntimeError(
                "Tutti i modelli LLM sono in cooldown temporaneo (rate-limit). "
                "Riprova tra ~60 secondi."
            )
        details = "\n".join([f"- {m}: {e}" for m, e in errors])
        raise RuntimeError(f"Tutti i modelli LLM in failover hanno fallito:\n{details}")


def _build_vectorstore_in_batches(documents, embeddings, batch_size: int, pause_sec: float, existing_vectorstore=None):
    vectorstore = existing_vectorstore
    total = len(documents)
    start = 0
    retries = 0
    max_retries = 3
    
    progress_bar = st.progress(0.0, text=f"Indicizzazione in corso... (0/{total} frammenti)")
    
    while start < total:
        batch = documents[start:start + batch_size]
        texts = [doc.page_content for doc in batch]
        metadatas = [doc.metadata for doc in batch]
        
        try:
            if vectorstore is None:
                vectorstore = FAISS.from_texts(texts, embeddings, metadatas=metadatas)
            else:
                vectorstore.add_texts(texts, metadatas=metadatas)
            
            start += batch_size
            retries = 0  # Resetta i tentativi se il batch va a buon fine
            
            current = min(start, total)
            progress_bar.progress(current / total, text=f"Indicizzazione in corso... ({current}/{total} frammenti)")
            
            if pause_sec > 0 and start < total:
                time.sleep(pause_sec)
        except Exception as exc:
            msg = str(exc).lower()
            if "429" in msg or "exhausted" in msg or "quota" in msg or "rate" in msg:
                if retries < max_retries:
                    retries += 1
                    st.toast(f"⏳ Quota embeddings esaurita ({start}/{total} frammenti). Pausa 60s (tentativo {retries}/{max_retries})...", icon="⏳")
                    time.sleep(60.0)
                else:
                    progress_bar.empty()
                    raise RuntimeError(f"Limite tentativi superato per errore quota: {exc}")
            else:
                progress_bar.empty()
                raise
    progress_bar.empty()
    return vectorstore


@st.cache_resource(show_spinner="Caricamento ricerca locale in corso...")
def init_local_chain():
    local_docs = init_local_documents()
    if not local_docs:
        return None
    return LocalSearchChain(local_docs, top_k=6)


@st.cache_resource(show_spinner="Caricamento corpus locale in corso...")
def init_local_documents():
    corpus_path = Path("albo_download/documenti_corpus.jsonl")
    if not corpus_path.exists():
        return None
    local_docs = _load_corpus_documents(corpus_path)
    if not local_docs:
        return None
    return local_docs


@st.cache_resource(show_spinner="Inizializzazione Gemini con retriever locale...")
def init_gemini_local_retriever_chain(llm_models):
    llm_models = tuple(llm_models)
    local_docs = init_local_documents()
    if not local_docs:
        return None
    retriever = LocalTokenRetriever(local_docs, top_k=6)
    return LLMFailoverRAGChain(
        retriever=retriever,
        prompt_template=PROMPT_TEMPLATE,
        llm_models=llm_models,
    )


@st.cache_resource(show_spinner="Caricamento e indicizzazione Gemini in corso...")
def init_rag_system(embedding_models, llm_models, embed_batch_size: int, embed_pause_sec: float, build_if_missing=True):
    embedding_models = tuple(embedding_models)
    llm_models = tuple(llm_models)

    faiss_index_path = Path("albo_download/faiss_index")
    faiss_manifest_path = Path("albo_download/faiss_index_manifest.json")
    corpus_path = Path("albo_download/documenti_corpus.jsonl")

    emb_ready, emb_init_errors = _instantiate_embeddings_candidates(embedding_models)
    if not emb_ready:
        details = "\n".join([f"- {m}: {e}" for m, e in emb_init_errors]) or "- nessun dettaglio"
        raise RuntimeError(
            "Nessun modello embeddings inizializzabile. Verifica GOOGLE_EMBEDDING_MODEL_PRIORITY.\n"
            f"Tentativi:\n{details}"
        )

    # Prova prima il load in sola lettura su un indice trusted per uno dei modelli disponibili
    for embedding_model, embeddings in emb_ready:
        if _index_is_trusted(faiss_index_path, faiss_manifest_path, embedding_model=embedding_model):
            try:
                vectorstore = FAISS.load_local(str(faiss_index_path), embeddings, allow_dangerous_deserialization=True)
                chain = LLMFailoverRAGChain(
                    retriever=vectorstore.as_retriever(search_kwargs={"k": 6}),
                    prompt_template=PROMPT_TEMPLATE,
                    llm_models=llm_models,
                )
                return chain, embedding_model
            except Exception:
                pass

    if not build_if_missing:
        return None, None

    if not corpus_path.exists():
        return None, None

    documents = _load_corpus_documents(corpus_path)
    if not documents:
        return None, None

    # Build con fallback tra modelli embedding e throttling per ridurre picchi quota
    build_errors = []
    for embedding_model, embeddings in emb_ready:
        try:
            vectorstore = _build_vectorstore_in_batches(
                documents=documents,
                embeddings=embeddings,
                batch_size=max(1, int(embed_batch_size)),
                pause_sec=max(0.0, float(embed_pause_sec)),
            )
            vectorstore.save_local(str(faiss_index_path))
            faiss_manifest_path.write_text(
                json.dumps(
                    _build_index_manifest(faiss_index_path, embedding_model=embedding_model),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            chain = LLMFailoverRAGChain(
                retriever=vectorstore.as_retriever(search_kwargs={"k": 6}),
                prompt_template=PROMPT_TEMPLATE,
                llm_models=llm_models,
            )
            return chain, embedding_model
        except Exception as exc:
            build_errors.append((embedding_model, str(exc)))

    details = "\n".join([f"- {m}: {e}" for m, e in build_errors]) or "- nessun dettaglio"
    raise RuntimeError(
        "Build indice embeddings fallita per tutti i modelli candidati.\n"
        f"Tentativi:\n{details}"
    )


st.sidebar.header("Modalita' Ricerca")
profile_name = st.sidebar.selectbox("Profilo quote", list(MODEL_PROFILES.keys()), index=0)
profile = MODEL_PROFILES[profile_name]

embedding_models = _unique_non_empty(
    _split_env_list(os.environ.get("GOOGLE_EMBEDDING_MODEL_PRIORITY", ""))
    or profile["embedding_models"]
    or DEFAULT_EMBEDDING_MODELS
)

llm_models = _unique_non_empty(
    _split_env_list(os.environ.get("GOOGLE_LLM_MODEL_PRIORITY", ""))
    or profile["llm_models"]
    or DEFAULT_LLM_MODELS
)

embed_batch_size = st.sidebar.slider(
    "Batch embedding (build indice)",
    min_value=10,
    max_value=500,
    value=int(profile["embed_batch_size"]),
    step=10,
)
embed_pause_sec = st.sidebar.slider(
    "Pausa batch embedding (s)",
    min_value=0.0,
    max_value=65.0,
    value=float(profile["embed_pause_sec"]),
    step=1.0,
)

use_gemini = st.sidebar.toggle(
    "Usa Gemini (consuma quota API)",
    value=USE_GEMINI_DEFAULT,
    help=(
        "Se disattivato usa solo ricerca locale (zero quota API). "
        "Se attivato carica indice esistente e puo' costruirlo su richiesta."
    ),
)

use_local_retriever_with_gemini = st.sidebar.toggle(
    "Gemini con retriever locale (zero quota embedding)",
    value=USE_LOCAL_RETRIEVER_WITH_GEMINI_DEFAULT,
    help=(
        "Quando l'indice FAISS non e' disponibile o la quota embedding e' finita, "
        "usa retrieval lessicale locale + risposta Gemini."
    ),
)

st.sidebar.caption("Priorita' LLM: " + " -> ".join(llm_models[:4]))
st.sidebar.caption("Priorita' Embedding: " + " -> ".join(embedding_models[:3]))

rag_chain = None
active_embedding_model = None

if use_gemini:
    google_api_key = (os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not google_api_key:
        st.warning(
            "GOOGLE_API_KEY non trovata: attivata modalita' locale. "
            "Aggiungi GOOGLE_API_KEY nel .env per usare Gemini."
        )
        rag_chain = init_local_chain()
    else:
        load_error = None
        # 1) prova load indice esistente (no build, riduce consumo quota)
        try:
            rag_chain, active_embedding_model = init_rag_system(
                embedding_models=tuple(embedding_models),
                llm_models=tuple(llm_models),
                embed_batch_size=embed_batch_size,
                embed_pause_sec=embed_pause_sec,
                build_if_missing=False,
            )
        except Exception as e:
            load_error = str(e)

        # 2) se manca indice: preferisci Gemini + retrieval locale (nessun embedding API)
        if rag_chain is None:
            if load_error:
                st.warning("Inizializzazione Gemini (solo load indice) non riuscita.")
                st.caption(f"Dettaglio errore API: {load_error}")

            if use_local_retriever_with_gemini:
                try:
                    rag_chain = init_gemini_local_retriever_chain(tuple(llm_models))
                except Exception as e:
                    st.warning("Init Gemini con retriever locale fallita: attivata modalita' locale.")
                    st.caption(f"Dettaglio errore API: {e}")
                    rag_chain = init_local_chain()

            st.info(
                "Indice embeddings non presente/non compatibile. "
                "Puoi continuare con retrieval locale oppure costruire ora l'indice Gemini."
            )
            if st.button("Costruisci indice Gemini adesso (usa quota embedding)"):
                try:
                    rag_chain, active_embedding_model = init_rag_system(
                        embedding_models=tuple(embedding_models),
                        llm_models=tuple(llm_models),
                        embed_batch_size=embed_batch_size,
                        embed_pause_sec=embed_pause_sec,
                        build_if_missing=True,
                    )
                except Exception as e:
                    st.warning("Build indice Gemini fallita.")
                    st.caption(f"Dettaglio errore API: {e}")
                    if rag_chain is None:
                        rag_chain = init_local_chain()
            elif rag_chain is None:
                rag_chain = init_local_chain()

        if isinstance(rag_chain, LLMFailoverRAGChain):
            if active_embedding_model:
                st.caption(
                    "Modello AI attivo con indice FAISS | embedding model: "
                    f"`{active_embedding_model}` | failover LLM: {len(rag_chain.llm_candidates)} modelli"
                )
                
                if st.button("🔄 Aggiorna indice con nuovi documenti"):
                    with st.spinner("Verifica nuovi documenti da indicizzare..."):
                        try:
                            corpus_path = Path("albo_download/documenti_corpus.jsonl")
                            all_docs = _load_corpus_documents(corpus_path)
                            
                            # Estrae i nomi dei PDF già presenti nel docstore di FAISS
                            vectorstore = rag_chain.retriever.vectorstore
                            existing_pdfs = {d.metadata.get("pdf_name") for d in vectorstore.docstore._dict.values()}
                            
                            # Filtra solo i documenti (frammenti) che provengono da PDF non ancora indicizzati
                            new_docs = [d for d in all_docs if d.metadata.get("pdf_name") not in existing_pdfs]
                            
                            if not new_docs:
                                st.info("✅ L'indice è già aggiornato! Nessun nuovo documento trovato.")
                            else:
                                emb_ready, _ = _instantiate_embeddings_candidates([active_embedding_model])
                                if emb_ready:
                                    _, embeddings = emb_ready[0]
                                    updated_vs = _build_vectorstore_in_batches(
                                        documents=new_docs,
                                        embeddings=embeddings,
                                        batch_size=int(embed_batch_size),
                                        pause_sec=float(embed_pause_sec),
                                        existing_vectorstore=vectorstore
                                    )
                                    faiss_index_path = Path("albo_download/faiss_index")
                                    faiss_manifest_path = Path("albo_download/faiss_index_manifest.json")
                                    updated_vs.save_local(str(faiss_index_path))
                                    faiss_manifest_path.write_text(
                                        json.dumps(
                                            _build_index_manifest(faiss_index_path, embedding_model=active_embedding_model),
                                            ensure_ascii=False,
                                            indent=2,
                                        ),
                                        encoding="utf-8",
                                    )
                                    st.success(f"✅ Aggiunti {len(new_docs)} nuovi frammenti all'indice!")
                                    time.sleep(2)
                                    st.rerun()
                                else:
                                    st.error("Impossibile inizializzare il modello di embedding per l'aggiornamento.")
                        except Exception as e:
                            st.error(f"Errore durante l'aggiornamento: {e}")
            else:
                st.caption(
                    "Modello AI attivo con retriever locale (no embedding API) | "
                    f"failover LLM: {len(rag_chain.llm_candidates)} modelli"
                )
else:
    st.sidebar.caption("Modalita' locale attiva: nessun consumo quota API.")
    rag_chain = init_local_chain()

if rag_chain is None:
    st.error(
        "Nessun corpus disponibile: file 'albo_download/documenti_corpus.jsonl' "
        "non trovato o vuoto."
    )
    st.stop()

CHAT_HISTORY_FILE = Path("albo_download/chat_history.json")

def load_chat_history():
    if CHAT_HISTORY_FILE.exists():
        try:
            return json.loads(CHAT_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_chat_history(messages):
    CHAT_HISTORY_FILE.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

# 4. Interfaccia Chat Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = load_chat_history()

if st.sidebar.button("🗑️ Cancella cronologia chat"):
    st.session_state.messages = []
    save_chat_history([])
    st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_question := st.chat_input("Chiedi qualcosa sui documenti (es. Quali ditte hanno avuto affidamenti diretti?)"):
    st.chat_message("user").markdown(user_question)
    st.session_state.messages.append({"role": "user", "content": user_question})
    save_chat_history(st.session_state.messages)

    with st.spinner("Ricerca nei documenti e ragionamento in corso..."):
        try:
            response = rag_chain.invoke(user_question)
            with st.chat_message("assistant"):
                st.markdown(response)
                if hasattr(rag_chain, "last_model") and rag_chain.last_model:
                    st.caption(f"Risposta generata con modello: `{rag_chain.last_model}`")
            st.session_state.messages.append({"role": "assistant", "content": response})
            save_chat_history(st.session_state.messages)
        except Exception as e:
            st.error(f"Errore durante l'interrogazione: {e}")
