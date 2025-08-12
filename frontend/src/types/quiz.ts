export interface QuizQuestion {
  id: string;
  q: string; // Question text (matches backend)
  question: string; // Alias for q
  options: Record<string, string>; // e.g., { A: 'Option 1', B: 'Option 2' }
  opts?: Record<string, string>; // Alias for options (matches backend)
  a: string; // Correct answer key (matches backend)
  correctAnswer: string; // Alias for a
  explanation: string;
}

export interface Quiz {
  id: string;
  topic: string;
  questions: QuizQuestion[];
  createdAt: string;
  updatedAt: string;
}

export interface QuizAnswer {
  [questionId: string]: string; // Maps question ID to selected option key (e.g., 'A')
}

export interface QuizResult {
  score: number;
  total: number;
  wrongAnswers: Array<{
    question: string;
    userAnswer: string;
    correctAnswer: string;
    explanation: string;
  }>;
}

export interface VideoItem {
  url: string;
  level: number;
  title: string;
  id?: string;
  thumbnail?: string;
  duration?: number;
}
