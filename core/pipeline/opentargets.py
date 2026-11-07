"""Small read-only client for the pinned Open Targets 26.09 recipes."""

import time

import httpx


URL = "https://api.platform.opentargets.org/api/v4/graphql"
# Copied from docs/engineering/build-reference.md A2; do not add datasource overrides.
ASSOC = '''query Assoc($id: String!, $i: Int!, $size: Int!) {
  disease(efoId: $id) {
    associatedTargets(page: {index: $i, size: $size}) {
      count
      rows { target { id approvedSymbol } score
             datatypeScores { id score } datasourceScores { id score } } } } }
'''


class OpenTargetsError(RuntimeError):
    """An upstream failure or incomplete response; never a guessed result."""


class OpenTargetsClient:
    def __init__(self, *, transport=None):
        self.http = httpx.Client(transport=transport, timeout=15)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.http.close()

    def request(self, method, url, **kwargs):
        """Retry transient read-only requests within one shared deadline."""
        deadline = time.monotonic() + 15
        for attempt in range(3):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise OpenTargetsError("Open Targets request exceeded 15 seconds")
                response = self.http.request(method, url, timeout=remaining, **kwargs)
                response.raise_for_status()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {
                    429, 502, 503, 504
                }:
                    raise OpenTargetsError(f"Open Targets HTTP {exc.response.status_code}") from exc
                if attempt == 2:
                    raise OpenTargetsError(f"Open Targets request failed after 3 attempts: {exc}") from exc
                delay = (0.25, 0.75)[attempt]
                if time.monotonic() + delay >= deadline:
                    raise OpenTargetsError("Open Targets request exceeded 15 seconds") from exc
                time.sleep(delay)
                continue
            return response

    def execute(self, query, variables):
        response = self.request("POST", URL, json={"query": query, "variables": variables})
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenTargetsError("Open Targets returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
            raise OpenTargetsError(f"Open Targets returned no usable data: {payload}")
        return payload["data"]

    def associations(self, disease_id, *, page_size=3000):
        """Fetch every row, failing if paging stops early or changes underneath us."""
        if not 1 <= page_size <= 3000:
            raise ValueError("page_size must be between 1 and 3000")
        rows = {}
        count = None
        # Equal-score rows can move across page boundaries. Recover missing IDs
        # with different boundaries, but never silently return a partial set.
        # Non-nested sizes move boundaries away from the same equal-score groups.
        sizes = (page_size, max(1, page_size * 73 // 100), max(1, page_size * 87 // 100))
        for size in dict.fromkeys(sizes):
            fetched, index = 0, 0
            while count is None or fetched < count:
                disease = self.execute(ASSOC, {"id": disease_id, "i": index, "size": size}).get("disease")
                if disease is None:
                    raise OpenTargetsError(f"Unknown disease ID: {disease_id}")
                page = disease["associatedTargets"]
                if count is None:
                    count = page["count"]
                    if not isinstance(count, int) or count < 0:
                        raise OpenTargetsError("Invalid association count")
                if page["count"] != count:
                    raise OpenTargetsError("Open Targets association count changed while paging")
                if not page["rows"] and fetched < count:
                    raise OpenTargetsError(f"Incomplete associations: received {len(rows)} of {count}")
                for row in page["rows"]:
                    target_id = row["target"]["id"]
                    previous = rows.get(target_id)
                    if previous is not None:
                        # Score arrays are sets by ID; their order varies by request.
                        changed = previous["target"] != row["target"] or previous["score"] != row["score"]
                        for field in ("datasourceScores", "datatypeScores"):
                            changed |= sorted(previous[field], key=lambda item: item["id"]) != sorted(
                                row[field], key=lambda item: item["id"]
                            )
                        if changed:
                            raise OpenTargetsError(f"Association changed while paging: {target_id}")
                    rows[target_id] = row
                fetched += len(page["rows"])
                if fetched > count or len(rows) > count:
                    raise OpenTargetsError("Open Targets returned more associations than count")
                index += 1
            if len(rows) == count:
                return list(rows.values())
        raise OpenTargetsError(f"Incomplete associations after paging recovery: received {len(rows)} of {count}")
