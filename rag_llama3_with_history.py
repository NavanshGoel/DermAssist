from langchain_community.document_loaders import WebBaseLoader
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.embeddings import CacheBackedEmbeddings
from langchain.storage import LocalFileStore
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage

import os
import warnings
warnings.filterwarnings('ignore')

os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGCHAIN_API_KEY"] = "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"

embed_model_id = 'sentence-transformers/all-MiniLM-L6-v2'

urls = [
    "https://www.aad.org/public/diseases/acne/diy/adult-acne-treatment",
    "https://www.aad.org/public/diseases/a-z/ringworm-treatment",
    "https://www.aad.org/public/everyday-care/hair-scalp-care/scalp/treat-dandruff",
]


def get_document_retriever():
    docs = [WebBaseLoader(url).load() for url in urls]
    docs_list = [item for sublist in docs for item in sublist]

    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=250, chunk_overlap=0
    )

    store = LocalFileStore("./cache/")

    core_embeddings_model = HuggingFaceEmbeddings(
        model_name=embed_model_id
    )

    embedder = CacheBackedEmbeddings.from_bytes_store(
        core_embeddings_model, store, namespace=embed_model_id
    )

    doc_splits = text_splitter.split_documents(docs_list)
    vector_store = FAISS.from_documents(documents=doc_splits, embedding=embedder)
    retriever = vector_store.as_retriever()

    return retriever


def get_qa_prompt():
    prompt = """You are an assistant for question-answering tasks. \
                Use the following pieces of retrieved context to answer the question. \
                If you don't know the answer, just say that you don't know. \
                Use three sentences maximum and keep the answer concise.\

                {context}"""

    return prompt


def get_retriever_prompt():
    prompt = """Given a chat history and the latest user question \
                    which might reference context in the chat history, formulate a standalone question \
                    which can be understood without the chat history. Do NOT answer the question, \
                    just reformulate it if needed and otherwise return it as is."""
    return prompt


class RAG:
    def __init__(self):
        self.llm = ChatOllama(model="llama3", temperature=0)
        self.retriever = get_document_retriever()
        self.llm_prompt = get_qa_prompt()
        self.retriever_prompt = get_retriever_prompt()
        self.chat_history = []

    def format_docs(self, documents):
        return "\n\n".join(doc.page_content for doc in documents)

    def generate_response(self, query):
        chat_history = self.chat_history
        retriever_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.retriever_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
            ]
        )

        llm_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.llm_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),
            ]
        )

        contextualize_q_chain = retriever_prompt | self.llm | StrOutputParser()

        def contextualized_question(inp: dict):
            if inp.get("chat_history"):
                return contextualize_q_chain
            else:
                return inp["input"]

        rag_chain = (
                RunnablePassthrough.assign(
                    context=contextualized_question | self.retriever | self.format_docs
                )
                | llm_prompt
                | self.llm
        )

        chain_response = rag_chain.invoke({"input": query, "chat_history": chat_history})
        llm_response = chain_response.to_json()["kwargs"]["content"]

        self.chat_history.append(HumanMessage(content=query))
        self.chat_history.append(llm_response)

        return llm_response


if __name__ == '__main__':
    rag = RAG()
    while True:
        input_query = input("Enter your question: ")
        if input_query.lower() == "exit":
            break
        print("\nLLM Response:")
        print(rag.generate_response(input_query), "\n")