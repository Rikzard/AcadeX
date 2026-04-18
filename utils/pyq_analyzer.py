import re

# -----------------------------
# STEP 1: Extract questions
# -----------------------------
def extract_questions(text):
    lines = text.lower().split("\n")
    questions = []

    for line in lines:
        line = line.strip()

        # Reduced minimum length to 10 to catch short questions like "what is dbms?"
        if len(line) < 10:
            continue

        if (
            "?" in line or
            line.startswith("explain") or
            line.startswith("define") or
            line.startswith("what") or
            line.startswith("write") or
            line.startswith("describe")
        ):
            questions.append(line)

    return questions


# -----------------------------
# STEP 2: Extract syllabus topics
# -----------------------------
def extract_topics(syllabus):
    topics = syllabus.lower().split("\n")
    return [t.strip() for t in topics if len(t.strip()) > 3]


# -----------------------------
# STEP 3: Matching logic
# -----------------------------
def match_score(question, topic):
    q_words = set(re.findall(r'\w+', question))
    t_words = set(re.findall(r'\w+', topic))

    return len(q_words & t_words)


# -----------------------------
# STEP 4: Main analyzer
# -----------------------------
def analyze(text, syllabus):
    questions = extract_questions(text)
    topics = extract_topics(syllabus)

    # Group identical questions to calculate frequency
    question_freqs = {}
    for q in questions:
        clean_q = q.strip()
        if clean_q not in question_freqs:
            question_freqs[clean_q] = 1
        else:
            question_freqs[clean_q] += 1

    results = []

    for q, freq in question_freqs.items():
        best_match_score = 0
        best_topic = None

        for t in topics:
            score = match_score(q, t)

            if score > best_match_score:
                best_match_score = score
                best_topic = t

        if best_match_score > 0:
            # Multiply string match score by frequency to establish true relevance
            overall_relevance = best_match_score * freq
            results.append({
                "question": q,
                "topic": best_topic,
                "score": overall_relevance,
                "frequency": freq
            })

    # Sort deeply by overall relevance score
    results.sort(key=lambda x: x["score"], reverse=True)

    return {
        "top_questions": results[:30]
    }