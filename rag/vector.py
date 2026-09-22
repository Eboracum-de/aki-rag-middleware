import uuid

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        PointStruct,
        PointIdsList,
        Filter,
        FieldCondition,
        MatchValue,
    )
except ImportError:  # optional when Qdrant is disabled in a lite deployment
    QdrantClient = None
    PointStruct = PointIdsList = Filter = FieldCondition = MatchValue = None


class VectorStore:

    def __init__(
        self,
        url: str,
        collection: str,
    ):
        if QdrantClient is None:
            raise RuntimeError("Qdrant support is not installed (missing 'qdrant-client' Python package)")
        self.client = QdrantClient(
            url=url
        )
        self.collection = collection


    @staticmethod
    def point_id(
        document_id: str,
        chunk_no: int,
    ) -> str:

        key = (
            f"nextcloud-rag:"
            f"{document_id}:"
            f"{chunk_no}"
        )

        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                key,
            )
        )


    def upsert(
        self,
        points: list[dict],
    ):

        if not points:
            return


        qdrant_points = [

            PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p["payload"],
            )

            for p in points
        ]


        self.client.upsert(
            collection_name=self.collection,
            points=qdrant_points,
            wait=True,
        )


    def delete_document(
        self,
        document_id: str,
        chunk_count: int,
    ):

        if chunk_count <= 0:
            return


        point_ids = [

            self.point_id(
                document_id,
                chunk_no,
            )

            for chunk_no in range(
                chunk_count
            )
        ]


        self.client.delete(
            collection_name=self.collection,
            points_selector=PointIdsList(
                points=point_ids,
            ),
            wait=True,
        )


    def search(
        self,
        vector: list[float],
        limit: int = 5,
        exclude_source_origins: list[str] | None = None,
        include_source_origins: list[str] | None = None,
        acl_user: str | None = None,
        acl_groups: list[str] | None = None,
    ):

        # Internal maintenance/smoke-test points must never become retrieval
        # candidates or answer evidence.  Web archive chunks stay indexable,
        # but are excluded from ordinary internal retrieval by source_origin.
        must_not = [
            FieldCondition(
                key="_rag_internal",
                match=MatchValue(value=True),
            )
        ]
        for origin in exclude_source_origins or []:
            value = str(origin or "").strip()
            if value:
                must_not.append(
                    FieldCondition(
                        key="source_origin",
                        match=MatchValue(value=value),
                    )
                )
        must = []

        origin_should = []
        for origin in include_source_origins or []:
            value = str(origin or "").strip()
            if value:
                origin_should.append(
                    FieldCondition(key="source_origin", match=MatchValue(value=value))
                )
        if origin_should:
            must.append(Filter(should=origin_should))

        username = str(acl_user or "").strip()
        if username and acl_groups is not None:
            acl_should = [
                FieldCondition(key="owner", match=MatchValue(value=username)),
                FieldCondition(key="users", match=MatchValue(value=username)),
            ]
            for group in acl_groups:
                value = str(group or "").strip()
                if value:
                    acl_should.append(
                        FieldCondition(key="groups", match=MatchValue(value=value))
                    )
            must.append(Filter(should=acl_should))

        internal_filter = Filter(must=must or None, must_not=must_not)

        result = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=internal_filter,
            limit=limit,
            with_payload=True,
        )

        return result.points


    def close(self):
        """
        HTTP-Verbindung zu Qdrant sauber schließen.
        """

        self.client.close()
