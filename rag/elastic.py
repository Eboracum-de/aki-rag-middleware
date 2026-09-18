import httpx

from rag.elasticsearch_client import httpx_options as elastic_httpx_options


class ElasticSource:
    def __init__(self, base_url: str, index: str, timeout: float = 60.0, cfg: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.index = index
        self.timeout = timeout
        self.httpx_options = elastic_httpx_options(cfg or {"elasticsearch": {}})

    def fetch_documents(self, limit: int = 20) -> list[dict]:
        url = f"{self.base_url}/{self.index}/_search"

        body = {
            "size": limit,
            "_source": [
                "title",
                "content",
                "hash",
                "source",
                "share_names",
                "attachment",
            ],
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "content"}}
                    ]
                }
            },
        }

        response = httpx.post(
            url,
            json=body,
            timeout=self.timeout,
            **self.httpx_options,
        )
        response.raise_for_status()

        docs = []

        for hit in response.json()["hits"]["hits"]:
            source = hit["_source"]
            content = source.get("content", "")

            if not content or not content.strip():
                continue

            docs.append(
                {
                    "id": hit["_id"],
                    "title": source.get("title", ""),
                    "content": content,
                    "hash": source.get("hash", ""),
                    "source": source.get("source", ""),
                    "share_names": source.get("share_names", {}),
                    "attachment": source.get("attachment", {}),
                }
            )

        return docs
