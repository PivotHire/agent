import chromadb


class ChromaDB:

    def __init__(self, name):
        self.name = name
        self.client = chromadb.PersistentClient(path="./chroma_data")
        #self.client = chromadb.HttpClient(host="YOUR_SERVER_HOSTNAME_OR_IP", port=8000) #for future hosting purposes


    def upsert(name, ids, embeddings, documents, metadatas):
        collection = self.client.get_or_create_collection(
            name=name,
            configuration={
                "hnsw": { #very modifiable for later testing
                    "space": "l2",
                    "ef_construction": 200
                }
            }
            )
        collection.upsert(
            documents=documents,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas #lets make this file type or some high level abstraction
        )
        return 0
    
    def query(self, name, query):
        collection = self.client.get_collection(name=name)
        results = collection.query(
            query_embeddings=query,
            n_results=10,
            include=["distances", "documents", "metadatas"]
            
            #more configuration options here
        )
        return results
