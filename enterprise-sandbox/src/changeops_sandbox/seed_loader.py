"""Load disclosed synthetic state from package resources."""

from importlib.resources import files

from pydantic import BaseModel


def load_seed[SeedModel: BaseModel](filename: str, model_type: type[SeedModel]) -> SeedModel:
    resource = files("changeops_sandbox.seed").joinpath(filename)
    return model_type.model_validate_json(resource.read_text(encoding="utf-8"))
