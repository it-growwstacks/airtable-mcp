# validators.py
# Layer 5 — Input Validation

from pydantic import BaseModel, Field, field_validator
from error_codes import Errors, ErrorDef
from airtable_client import CLIENT_STATUS_VALUES, PROJECT_STATUS_VALUES, TASK_STATUS_VALUES


class ValidationError(Exception):
    def __init__(self, error: ErrorDef, message: str | None = None):
        self.error = error
        self.message = message or error.message
        super().__init__(self.message)


def validate_input(model_class, raw_input: dict) -> object:
    try:
        return model_class(**raw_input)
    except Exception as e:
        raise ValidationError(
            Errors.INVALID_PARAMETER,
            message=f"{Errors.INVALID_PARAMETER.message} {str(e)}"
        )


class GetClientInput(BaseModel):
    client_ref: str = Field(min_length=1, max_length=200)

    @field_validator("client_ref")
    @classmethod
    def strip(cls, v): return v.strip()


class ListClientsInput(BaseModel):
    status: str = Field(default="")
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        v = v.strip()
        if v and v not in CLIENT_STATUS_VALUES:
            raise ValueError(f"'{v}' is not a valid Client Status. Valid values: {sorted(CLIENT_STATUS_VALUES)}")
        return v


class SearchClientsInput(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


class GetProjectInput(BaseModel):
    project_ref: str = Field(min_length=1, max_length=200)

    @field_validator("project_ref")
    @classmethod
    def strip(cls, v): return v.strip()


class ListProjectsInput(BaseModel):
    status: str = Field(default="")
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        v = v.strip()
        if v and v not in PROJECT_STATUS_VALUES:
            raise ValueError(f"'{v}' is not a valid Project Status. Valid values: {sorted(PROJECT_STATUS_VALUES)}")
        return v


class GetClientProjectsInput(BaseModel):
    client_ref: str = Field(min_length=1, max_length=200)

    @field_validator("client_ref")
    @classmethod
    def strip(cls, v): return v.strip()


class GetTaskInput(BaseModel):
    task_ref: str = Field(min_length=1, max_length=200)

    @field_validator("task_ref")
    @classmethod
    def strip(cls, v): return v.strip()


class ListTasksByStatusInput(BaseModel):
    status: str = Field(min_length=1)
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        v = v.strip()
        if v not in TASK_STATUS_VALUES:
            raise ValueError(f"'{v}' is not a valid Task Status. Valid values: {sorted(TASK_STATUS_VALUES)}")
        return v


class SearchTasksInput(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)

class GetProjectTasksInput(BaseModel):
    project_ref: str = Field(min_length=1, max_length=200)

    @field_validator("project_ref")
    @classmethod
    def strip(cls, v): return v.strip()


class GetProjectTeamInput(BaseModel):
    project_ref: str = Field(min_length=1, max_length=200)

    @field_validator("project_ref")
    @classmethod
    def strip(cls, v): return v.strip()