export interface QuestionOption {
  [key: string]: string; // e.g., { A: 'Option 1', B: 'Option 2' }
}

export interface Question {
  q: string;
  a: string;
  opts: QuestionOption;
  explanation?: string;
}

export interface VideoRequest {
  topic: string;
  questions: Question[];
  answers: Record<string, string>;
}

export interface VideoResponse {
  videos: Array<{
    url: string;
    type: string;
    [key: string]: unknown; // For any additional properties
  }>;
  [key: string]: unknown; // For any additional properties
}

export interface ApiError extends Error {
  status?: number;
  details?: string;
}
