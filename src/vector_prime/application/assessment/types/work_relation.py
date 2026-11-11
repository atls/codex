from enum import StrEnum


class WorkRelation(StrEnum):
    DISCUSSION = "discussion"
    EXECUTION = "execution"
    EXPLICIT_RESELECTION = "explicit_reselection"
    UNCERTAIN = "uncertain"
