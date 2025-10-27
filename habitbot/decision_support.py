from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Union


class AnswerProvider(Protocol):
    def __call__(self, question: str) -> bool: ...


DecisionResult = Union["DecisionNode", str, Callable[[], str]]


@dataclass(frozen=True)
class DecisionNode:
    """A binary decision step consisting of a question and two possible branches."""

    question: str
    yes: DecisionResult
    no: DecisionResult


def decision_point(question: str, yes: DecisionResult, no: DecisionResult) -> DecisionNode:
    """
    Create a decision point with a question and branches for the user's answer.

    Branch values can be:
    * another DecisionNode (to continue asking follow-up questions);
    * a string message describing the outcome;
    * a zero-argument callable returning a string (useful for dynamic messages).
    """

    return DecisionNode(question=question, yes=yes, no=no)


def evaluate(node: DecisionResult, answer_provider: AnswerProvider) -> str:
    """
    Traverse a decision tree until a terminal result (string or callable) is reached.

    Args:
        node: the decision to evaluate (node, string, or callable).
        answer_provider: callable returning True/False for a question.

    Returns:
        Final textual recommendation produced by the tree.
    """

    current: DecisionResult = node
    while True:
        if isinstance(current, DecisionNode):
            branch = current.yes if answer_provider(current.question) else current.no
            current = branch
            continue
        if callable(current):
            return current()
        return current
