export interface QuizQuestion {
  id: string;
  question: string;
  options: Record<string, string>; // e.g., { A: 'Option 1', B: 'Option 2' }
  correctAnswer: string; // The key of the correct option (e.g., 'A')
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
