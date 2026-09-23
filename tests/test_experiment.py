from sc_rd.experiment import Experiment


def test_experiment_id_is_deterministic_for_same_method():
    a = Experiment("x", "h", "s", "d", {"fee": 0.1})
    b = Experiment("x", "h", "s", "d", {"fee": 0.1})
    assert a.experiment_id == b.experiment_id


def test_experiment_id_changes_when_assumption_changes():
    a = Experiment("x", "h", "s", "d", {"fee": 0.1})
    b = Experiment("x", "h", "s", "d", {"fee": 0.2})
    assert a.experiment_id != b.experiment_id
