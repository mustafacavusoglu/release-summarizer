from dataclasses import dataclass


@dataclass
class GithubSource:
    """GitHub Releases API üzerinden takip edilen kaynak."""
    name: str
    slug: str
    repo: str          # "org/repo" formatında
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "source_type": "github",
            "config": {"repo": self.repo},
            "enabled": self.enabled,
        }


@dataclass
class UrlSource:
    """RSS feed veya herhangi bir release sayfası URL'si üzerinden takip edilen kaynak."""
    name: str
    slug: str
    url: str           # RSS feed veya release/changelog sayfası
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slug": self.slug,
            "source_type": "url",
            "config": {"url": self.url},
            "enabled": self.enabled,
        }


DEFAULT_SOURCES: list[GithubSource | UrlSource] = [
    GithubSource(name="MLflow",                   slug="mlflow",        repo="mlflow/mlflow"),
    GithubSource(name="Qdrant",                   slug="qdrant",        repo="qdrant/qdrant"),
    GithubSource(name="OpenShift AI",             slug="openshift-ai",  repo="opendatahub-io/opendatahub-operator"),
    GithubSource(name="Red Hat AI (InstructLab)", slug="redhatai",      repo="instructlab/instructlab"),
    GithubSource(name="Ray",                      slug="ray",           repo="ray-project/ray"),
    GithubSource(name="KServe",                   slug="kserve",        repo="kserve/kserve"),
    GithubSource(name="Docker (Moby)",            slug="docker",        repo="moby/moby"),
    GithubSource(name="Kubernetes",               slug="kubernetes",    repo="kubernetes/kubernetes"),
]
