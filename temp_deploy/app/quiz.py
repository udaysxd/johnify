from fastapi import APIRouter

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

def mock_test():
    """Return a list of quiz questions with detailed information."""
    return [
        {
            "q": "What is the chemical symbol for water?",
            "opts": ["a) H2O", "b) CO2", "c) O2", "d) NaCl"],
            "a": "a",
            "explanation": "Water is composed of two hydrogen atoms and one oxygen atom, giving it the chemical formula H₂O."
        },
        {
            "q": "Which organelle is known as the powerhouse of the cell?",
            "opts": ["a) Nucleus", "b) Mitochondria", "c) Ribosome", "d) Chloroplast"],
            "a": "b",
            "explanation": "Mitochondria are often called the 'powerhouses' of the cell because they generate most of the cell's supply of ATP, used as a source of chemical energy."
        },
        {
            "q": "What is Newton's third law of motion?",
            "opts": [
                "a) Force equals mass times acceleration (F=ma)",
                "b) For every action, there is an equal and opposite reaction",
                "c) An object in motion stays in motion unless acted upon by an external force",
                "d) Energy cannot be created or destroyed, only transformed"
            ],
            "a": "b",
            "explanation": "Newton's third law states that for every action, there is an equal and opposite reaction. This means that any force exerted onto a body will create a force of equal magnitude but in the opposite direction on the object that exerted the first force."
        },
        {
            "q": "What is the main gas responsible for the greenhouse effect?",
            "opts": ["a) Oxygen", "b) Nitrogen", "c) Carbon dioxide", "d) Hydrogen"],
            "a": "c",
            "explanation": "While several gases contribute to the greenhouse effect, carbon dioxide (CO₂) is the primary greenhouse gas emitted through human activities such as burning fossil fuels and deforestation."
        },
        {
            "q": "Which process do plants use to make their own food?",
            "opts": ["a) Photosynthesis", "b) Respiration", "c) Transpiration", "d) Fermentation"],
            "a": "a",
            "explanation": "Photosynthesis is the process by which green plants and some other organisms use sunlight to synthesize foods with the help of chlorophyll. In this process, carbon dioxide and water are converted into glucose and oxygen."
        },
        {
            "q": "What is the unit of electric current?",
            "opts": ["a) Volt", "b) Ohm", "c) Ampere", "d) Watt"],
            "a": "c",
            "explanation": "The ampere (symbol: A) is the SI base unit of electric current, representing the flow of electric charge across a surface at the rate of one coulomb per second."
        },
        {
            "q": "What type of bond involves the sharing of electrons between atoms?",
            "opts": ["a) Ionic bond", "b) Covalent bond", "c) Metallic bond", "d) Hydrogen bond"],
            "a": "b",
            "explanation": "A covalent bond is a chemical bond that involves the sharing of electron pairs between atoms. These electron pairs are known as shared pairs or bonding pairs."
        },
        {
            "q": "What is the speed of light in a vacuum?",
            "opts": [
                "a) 3 × 10⁶ m/s (3 million meters per second)",
                "b) 3 × 10⁸ m/s (300 million meters per second)",
                "c) 3 × 10¹⁰ m/s (30 billion meters per second)",
                "d) 3 × 10⁵ m/s (300,000 meters per second)"
            ],
            "a": "b",
            "explanation": "The speed of light in a vacuum is exactly 299,792,458 meters per second (approximately 3 × 10⁸ m/s). This is a fundamental constant of nature and the maximum speed at which all conventional communication and matter can travel."
        },
        {
            "q": "Which vitamin is produced when skin is exposed to sunlight?",
            "opts": ["a) Vitamin A", "b) Vitamin C", "c) Vitamin D", "d) Vitamin K"],
            "a": "c",
            "explanation": "Vitamin D is produced in the skin through a chemical reaction that depends on sun exposure (specifically UVB radiation). This is why it's often called the 'sunshine vitamin.'"
        },
        {
            "q": "What is the formula for calculating density?",
            "opts": [
                "a) Mass / Volume",
                "b) Volume / Mass",
                "c) Mass × Volume",
                "d) Mass + Volume"
            ],
            "a": "a",
            "explanation": "Density is defined as mass per unit volume. The formula is: Density = Mass ÷ Volume. Common units include g/cm³ for solids and liquids, and g/L for gases."
        }
    ]

@router.get("/questions")
async def get_questions():
    """Endpoint to get all quiz questions."""
    return mock_test()

def administer(answers):
    """
    Grade quiz answers and identify wrong questions with detailed feedback.
    
    Args:
        answers: List of answer choices (a, b, c, or d) for each question
        
    Returns:
        dict: Contains score, total questions, wrong indices, and detailed wrong questions
    """
    questions = mock_test()
    score = 0
    wrong_indices = []
    wrong_questions = []
    
    print(f"\n📝 Grading answers: {answers}")
    
    for i, answer in enumerate(answers):
        if i >= len(questions):
            print(f"⚠️ More answers ({len(answers)}) than questions ({len(questions)})")
            break
            
        question = questions[i]
        correct = question["a"]
        user_answer = answer.strip().lower() if answer else ""
        
        print(f"  Q{i+1}: Given '{user_answer}', Correct is '{correct}'", end="")
        
        if user_answer == correct.lower():
            score += 1
            print(" ✅")
        else:
            # Get the full text of the correct answer
            correct_opt_index = ord(correct.lower()) - ord('a')
            correct_answer_text = question["opts"][correct_opt_index][3:] if 0 <= correct_opt_index < len(question["opts"]) else ""
            
            # Get the user's selected answer text
            user_answer_text = ""
            if user_answer:
                user_opt_index = ord(user_answer[0].lower()) - ord('a')
                if 0 <= user_opt_index < len(question["opts"]):
                    user_answer_text = question["opts"][user_opt_index][3:]
            
            # Create a detailed question object with explanation
            wrong_question = {
                "question": question["q"],
                "correct_answer": correct,
                "user_answer": user_answer if user_answer else "(No answer provided)",
                "options": question["opts"],
                "explanation": question.get("explanation", ""),
                "correct_answer_text": correct_answer_text,
                "user_answer_text": user_answer_text,
                "question_number": i + 1
            }
            wrong_indices.append(i)
            wrong_questions.append(wrong_question)
            print(f" ❌ (Adding to wrong answers)")
    
    print(f"🎯 Score: {score}/{len(questions)}")
    print(f"❌ Wrong answers: {len(wrong_questions)}")
    
    return {
        "score": score,
        "total_questions": len(questions),
        "wrong_indices": wrong_indices,
        "wrong_questions": wrong_questions,
        "percentage": int((score / len(questions)) * 100) if questions else 0
    }

# Export the router
__all__ = ["router"]
