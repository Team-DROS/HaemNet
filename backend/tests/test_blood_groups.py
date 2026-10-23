from backend.services.blood_groups import request_groups


def test_positive_recruitment():
    assert request_groups('All positive') == ('A+', 'B+', 'AB+', 'O+')


def test_negative_recruitment():
    assert request_groups('All negative') == ('A-', 'B-', 'AB-', 'O-')


def test_individual_group_unchanged():
    assert request_groups('O-') == ('O-',)
