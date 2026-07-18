from datetime import datetime, timezone

import requests

from alpha_os.core.models import GovernanceProposal, GovernanceSnapshot

SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"

_PROPOSALS_QUERY = """
query Proposals($space: String!) {
  proposals(first: 20, orderBy: "created", orderDirection: desc, where: {space: $space}) {
    id
    title
    start
    end
    state
    link
  }
}
"""


class SnapshotGovernanceAdapter:
    """Snapshot.org, gratis y sin API key (GraphQL público). El espacio DAO
    lo declara quien consulta (ej. "aavedao.eth", "ens.eth") — no se
    preselecciona qué DAO "importa" para ninguna narrativa."""

    def get_proposals(self, space: str) -> GovernanceSnapshot:
        try:
            response = requests.post(
                SNAPSHOT_GRAPHQL_URL,
                json={"query": _PROPOSALS_QUERY, "variables": {"space": space}},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return GovernanceSnapshot(space=space)

        raw_proposals = (data.get("data") or {}).get("proposals") or []
        proposals = [
            GovernanceProposal(
                proposal_id=p["id"],
                space=space,
                title=p["title"],
                state=p["state"],
                start=datetime.fromtimestamp(p["start"], tz=timezone.utc),
                end=datetime.fromtimestamp(p["end"], tz=timezone.utc),
                url=p.get("link"),
            )
            for p in raw_proposals
            if p.get("id") and p.get("title") is not None
        ]
        return GovernanceSnapshot(space=space, proposals=proposals)
