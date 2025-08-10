'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import VideoPlayer from '@/components/VideoPlayer';
import Header from '@/components/Header';
import type { VideoItem } from '@/types/quiz';

interface QuizQuestion {
  id: string;
  question: string;
  correctAnswer: string;
  options: Record<string, string>;
  explanation?: string;
  q?: string;
  a?: string;
  opts?: Record<string, string>;
}

interface QuizData {
  questions: QuizQuestion[];
  topic: string;
}

interface WrongAnswer {
  question: string;
  correctAnswer: string;
  userAnswer: string;
}

interface QuizResult {
  score: number;
  total: number;
  wrongAnswers: WrongAnswer[];
}

interface QuizAnswer {
  [key: string]: string;
}

export default function QuizPage() {
  const { data: _session } = useSession();
  const router = useRouter();
  const [isClient, setIsClient] = useState(false);
  const [topic, setTopic] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [quiz, setQuiz] = useState<QuizData | null>(null);
  const [answers, setAnswers] = useState<QuizAnswer>({});
  const [result, setResult] = useState<QuizResult | null>(null);

  // Set isClient to true after component mounts (client-side only)
  useEffect(() => {
    setIsClient(true);
  }, []);

  // Handle authentication and redirect if needed
  useEffect(() => {
    if (_session === null) {
      router.push('/auth/signin');
    }
  }, [_session, router]);

  // Generate quiz based on topic
  const generateQuiz = useCallback(async () => {
    if (!topic.trim()) return;

    setIsLoading(true);
    setError(null);
    setQuiz(null);
    setAnswers({});
    setResult(null);

    try {
      const response = await fetch('/api/quiz', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ topic, numQuestions: 3 }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to generate quiz');
      }

      const data: QuizData = await response.json();
      // Normalize options for all questions
      if (data.questions) {
        data.questions = data.questions.map((q: Partial<QuizQuestion> & { options?: Record<string, string> }, idx: number) => {
          const opts = q.options || q.opts || {};
          // Find the key whose value matches q.a or q.correctAnswer (case-insensitive)
          let correctKey = '';
          if (q.a) {
            correctKey = Object.entries(opts).find(
              ([, value]) => String(value).toLowerCase() === String(q.a).toLowerCase()
            )?.[0] || '';
          } else if (q.correctAnswer) {
            correctKey = Object.entries(opts).find(
              ([, value]) => String(value).toLowerCase() === String(q.correctAnswer).toLowerCase()
            )?.[0] || '';
          }
          // Always set all required fields, fallback if missing
          const questionId = q.id || `q-${idx}`;
          const questionText = q.q || q.question || `Question ${idx + 1}`;
          const answerText = q.a || q.correctAnswer || (correctKey ? opts[correctKey] : '');
          
          const normalizedQuestion: QuizQuestion = {
            id: questionId,
            question: questionText,
            correctAnswer: correctKey,
            options: opts,
            q: questionText,
            a: answerText,
            opts: opts,
            explanation: q.explanation
          };
          
          return normalizedQuestion;
        });
      }
      setQuiz(data);
    } catch (err) {
      const error = err as Error;
      console.error('Error generating quiz:', error);
      setError(error.message || 'Failed to generate quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [topic]);

  // Alias for generateQuiz for better readability
  const startQuiz = useCallback(() => {
    return generateQuiz();
  }, [generateQuiz]);

  // Handle answer selection
  const handleAnswer = useCallback((questionIdx: number, answer: string) => {
    setAnswers((prev: QuizAnswer) => ({
      ...prev,
      [questionIdx]: answer
    }));
  }, []);

  // Generate video based on quiz results
  const generateVideo = useCallback(async () => {
    if (!result || isGeneratingVideo || !quiz) return;

    setIsGeneratingVideo(true);
    setVideos([]);
    setError(null);

    try {
      // Prepare answers as a list in order of questions
      const answerList = quiz.questions.map((q, idx) => answers[idx] || '');

      // Send the original questions array as-is
      const response = await fetch('/api/generate-video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          topic,
          answers: answerList,
          questions: quiz.questions // send full objects for backend grading/slidegen
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to generate video');
      }

      const data: { videos?: VideoItem[]; error?: string; details?: string; message?: string } = await response.json();
      console.log('Video generation response:', data);

      if (data.videos?.length) {
        setVideos(data.videos);
      } else if (data.error) {
        throw new Error(data.details || data.error || 'Failed to generate videos');
      } else {
        throw new Error('No videos were generated. Please try again.');
      }
    } catch (err) {
      const error = err as Error;
      console.error('Error generating video:', error);
      setError(error.message || 'Failed to generate video. Please try again.');
      
      // If we have a 504 Gateway Timeout, suggest the user to wait
      const errorMessage = error.message || '';
      if (errorMessage.includes('504') || errorMessage.includes('timeout')) {
        setError('The video generation is taking longer than expected. Your videos are still being processed and will be available shortly.');
      }
    } finally {
      setIsGeneratingVideo(false);
    }
  }, [result, isGeneratingVideo, quiz, answers, topic]);

  // Submit quiz and get results from backend
  const submitQuiz = useCallback(async () => {
    if (!quiz) return;
    setIsLoading(true);
    setError(null);
    try {
      // Prepare answers as a list in order of questions
      const answerList = quiz.questions.map((q, idx) => {
        const id = q.id || idx.toString();
        // Default to empty string if not answered
        return answers[id] || '';
      });
      const response = await fetch('/api/grade_quiz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: answerList, questions: quiz.questions }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to grade quiz');
      }
      const data = await response.json();
      // Map backend result to frontend QuizResult
      const quizResult: QuizResult = {
        score: data.score,
        total: data.total_questions,
        wrongAnswers: (data.wrong_questions || []).map((wq: Record<string, string>) => ({
          question: wq.question,
          userAnswer: wq.user_answer_text || wq.user_answer,
          correctAnswer: wq.correct_answer_text || wq.correct_answer,
          explanation: wq.explanation || '',
        })),
      };
      setResult(quizResult);
      // Only generate video if there are wrong answers
      if (quizResult.wrongAnswers.length > 0) {
        console.log('Generating video for wrong answers...');
        await generateVideo();
      } else {
        console.log('All answers correct! No video needed.');
      }
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to grade quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [answers, generateVideo, quiz]);

  // Check video accessibility when videos change (client-side only)
  useEffect(() => {
    if (!isClient) return;
    
    console.log('Videos updated:', videos);
    
    // Check accessibility for each video
    videos.forEach(video => {
      if (video.url) {
        fetch(video.url, { method: 'HEAD' })
          .then(res => {
            console.log(`Video ${video.level} accessibility check:`, {
              status: res.status,
              statusText: res.statusText,
              contentType: res.headers.get('content-type'),
              contentLength: res.headers.get('content-length')
            });
          })
          .catch(err => {
            console.error(`Error accessing video ${video.level}:`, err);
          });
      }
    });
  }, [videos, isClient]);

if (result) {
  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-3xl mx-auto">
        {error && (
          <div className="bg-red-50 border-l-4 border-red-500 p-4 mb-6 rounded">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            </div>
          </div>
        )}
        
        <div className="bg-white p-6 rounded-lg shadow-md mb-8">
          <h2 className="text-2xl font-bold text-center mb-6">Assessment Results</h2>
          <div className="text-center mb-6">
            <p className="text-4xl font-bold text-indigo-600 mb-2">
              {result.score} / {result.total}
            </p>
            <p className="text-gray-600">
              {Math.round((result.score / result.total) * 100)}% Correct
            </p>
          </div>
            
            {result.wrongAnswers.length > 0 ? (
              <div className="mb-6">
                <h3 className="text-lg font-medium mb-3">Areas for Improvement:</h3>
                <ul className="space-y-2 text-sm text-gray-700">
                  {result.wrongAnswers.map((wrong: WrongAnswer, index: number) => (
                    <li key={index} className="flex items-start">
                      <span className="text-red-500 mr-2">•</span>
                      <span>{wrong.question}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="mb-6 p-4 bg-green-50 text-green-700 rounded-md">
                <p className="font-medium">🎉 Perfect score! You&apos;ve mastered this topic.</p>
                <p className="text-sm mt-1">Would you like to explore more advanced content?</p>
              </div>
            )}
            
            <button
              onClick={generateVideo}
              disabled={isGeneratingVideo || videos.length > 0}
              className={`w-full bg-blue-600 text-white py-3 px-4 rounded-md hover:bg-blue-700 transition flex items-center justify-center ${
                isGeneratingVideo || videos.length > 0 ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {isGeneratingVideo ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Generating learning videos...
                </>
              ) : videos.length > 0 ? (
                'Videos Ready!'
              ) : (
                'Generate Learning Videos'
              )}
            </button>
            
            <div className="mt-4 flex space-x-3">
              <button
                onClick={() => {
                  setQuiz(null);
                  setResult(null);
                  setAnswers({});
                  setVideos([]);
                }}
                className="flex-1 bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 transition"
              >
                Try Another Assessment
              </button>
              
              <Link
                href="/"
                className="flex-1 text-center bg-white border border-gray-300 text-gray-700 py-2 px-4 rounded-md hover:bg-gray-50 transition"
              >
                Back to Home
              </Link>
            </div>
          </div>

          {/* Video Player Section */}
          {videos.length > 0 && (
            <div className="bg-white p-6 rounded-lg shadow-md">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold">Your AI Tutor Videos</h2>
                <div className="text-sm text-gray-500">
                  {videos.length} video{videos.length !== 1 ? 's' : ''} available
                </div>
              </div>
              
              <div className="bg-gray-50 p-4 rounded-lg">
                <VideoPlayer 
                  videos={videos}
                  initialLevel={Math.min(3, videos.length)} // Default to level 3 or highest available
                  onVideoChange={(video: { url: string; level: number; title: string }) => {
                    console.log('Video changed:', video);
                  }}
                />
              </div>
              

            </div>
          )}
        </div>
      </div>
    );
  }

  if (quiz) {
    return (
      <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-3xl font-bold text-center mb-8">Assessment: {topic}</h1>
          
          <div className="space-y-8">
            {quiz.questions.map((q: QuizQuestion, index: number) => (
              <div key={index} className="bg-white p-6 rounded-lg shadow">
                <h3 className="text-lg font-medium mb-4">
                  {index + 1}. {q.q}
                </h3>
                <div className="space-y-2">
                  {Object.entries(q.opts || {}).map(([key, value]) => (
                    <label key={key} className="block">
                      <input
                        type="radio"
                        name={`question-${index}`}
                        className="mr-2"
                        checked={answers[index] === key}
                        onChange={() => handleAnswer(index, key)}
                      />
                      {value as string}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-8 flex justify-end">
            <button
              onClick={submitQuiz}
              className="bg-indigo-600 text-white py-2 px-6 rounded-md hover:bg-indigo-700 transition"
              disabled={Object.keys(answers).length !== quiz.questions.length}
            >
              Submit
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />
      <div className="flex items-center justify-center p-4 pt-20">
        <div className="bg-white p-8 rounded-lg shadow-md max-w-md w-full">
          <h1 className="text-2xl font-bold text-center mb-6">Create your personal AI tutor</h1>
          
          <div className="mb-6">
            <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-1">
              What do you need help with?
            </label>
            <input
              type="text"
              id="topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g., Python programming, World History, etc."
              className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-indigo-500 focus:border-indigo-500"
              onKeyDown={(e) => e.key === 'Enter' && startQuiz()}
            />
          </div>

          <button
            onClick={startQuiz}
            disabled={!topic.trim() || isLoading}
            className={`w-full bg-indigo-600 text-white py-3 px-4 rounded-md hover:bg-indigo-700 transition flex items-center justify-center ${
              !topic.trim() || isLoading ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {isLoading ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Generating Quick Assessment...
              </>
            ) : (
              'Start'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}