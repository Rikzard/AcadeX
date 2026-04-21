from app import app

with app.test_client() as c:
    # Teacher login
    c.post('/login', data={'username': 'teacher_user', 'password': 'teacher123'})
    r = c.get('/dashboard')
    print(f"Teacher dashboard status: {r.status_code}")
    body = r.data.decode('utf-8', errors='replace')
    assert 'Pending Submissions' in body, "Missing teacher metric card"
    assert 'Average Class Performance' in body, "Missing insights section"
    assert 'Action Center' in body, "Missing action center"
    print("Teacher view: All sections present ✓")

with app.test_client() as c:
    # Student login
    c.post('/login', data={'username': 'student_user', 'password': 'student123'})
    r = c.get('/dashboard')
    print(f"Student dashboard status: {r.status_code}")
    body = r.data.decode('utf-8', errors='replace')
    assert 'Mock Test Average' in body, "Missing student metric card"
    assert 'Quick Access' in body, "Missing quick access panel"
    assert 'Study Focus' in body, "Missing focus topics"
    print("Student view: All sections present ✓")

print("\nAll checks passed!")
