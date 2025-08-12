'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/providers/AuthProvider';
import LoadingState from '@/components/LoadingState';

// Define types
interface QuizQuestion {
  id: string;
  question: string;
  correctAnswer: string;
  options: Record<string, string>;
  explanation?: string;
}

interface QuizData {
  questions: QuizQuestion[];
  topic: string;
}

interface QuizResult {
  score: number;
  total: number;
  wrongAnswers: Array<{
    question: string;
    correctAnswer: string;
    userAnswer: string;
    explanation?: string;
  }>;
}

function QuizPageContent() {
  const router = useRouter();
  const { user } = useAuth();
  const isAuthenticated = !!user;
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [topic, setTopic] = useState('');
  const [quiz, setQuiz] = useState<QuizData | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    setIsClient(true);
  }, []);

  useEffect(() => {
    if (isClient && !isAuthenticated) {
      router.push('/auth/signin');
    }
  }, [isClient, isAuthenticated, router]);

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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, numQuestions: 3 }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to generate quiz');
      }

      const responseData = await response.json();
      console.log('Raw API response:', responseData);
      
      // Log the structure of the first question if it exists
      if (responseData.questions && responseData.questions.length > 0) {
        console.log('First question structure:', {
          id: responseData.questions[0].id,
          question: responseData.questions[0].question,
          options: responseData.questions[0].options,
          optionsType: typeof responseData.questions[0].options,
          optionsKeys: responseData.questions[0].options ? Object.keys(responseData.questions[0].options) : 'no options',
          entries: responseData.questions[0].options ? Object.entries(responseData.questions[0].options) : 'no entries'
        });
      }
      
      // Transform the data to match our QuizData interface
      const quizData: QuizData = {
        topic: responseData.topic || 'General Knowledge',
        questions: (responseData.questions || []).map((q: any, index: number) => {
          console.log('Processing question:', q);
          return {
            id: q.id || `question-${index}`,
            question: q.q || `Question ${index + 1}`,
            correctAnswer: q.a || '',
            options: q.opts || {},
            explanation: q.explanation
          };
        })
      };
      
      console.log('Processed quiz data:', JSON.stringify(quizData, null, 2));
      setQuiz(quizData);
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to generate quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [topic]);

  const generateVideo = async () => {
    if (!quiz) return;
    
    // Check if we have a result with wrong answers
    if (result) {
      // If there are no wrong answers, no need to generate a video
      if (result.wrongAnswers.length === 0) {
        setVideoError('Great job! All answers are correct. No video needed.');
        return;
      }
    }
    
    setIsGeneratingVideo(true);
    setVideoError(null);
    setVideoUrl(null);
    
    try {
      // Format answers as an object with question indices as keys
      const formattedAnswers: Record<string, string> = {};
      
      // Format questions to match backend expectations
      const formattedQuestions = quiz.questions.map((q, index) => {
        // Format options as { A: 'option1', B: 'option2', ... }
        const formattedOpts: Record<string, string> = {};
        if (q.options && typeof q.options === 'object') {
          Object.entries(q.options).forEach(([key, value], idx) => {
            const optionKey = String.fromCharCode(65 + idx); // A, B, C, etc.
            formattedOpts[optionKey] = String(value);
          });
        }
        
        // Store the answer for this question
        const answerKey = answers[q.id];
        if (answerKey !== undefined) {
          // Convert answer to letter (0->'a', 1->'b', etc.)
          const letterAnswer = String.fromCharCode(97 + parseInt(answerKey, 10));
          formattedAnswers[index] = letterAnswer;
        }
        
        // Return formatted question
        return {
          q: q.question || 'No question text',
          a: q.correctAnswer || '',
          opts: formattedOpts,
          explanation: q.explanation || `Explanation for question ${index + 1}`
        };
      });
      
      console.log('Sending to generate-video API:', {
        topic: quiz.topic,
        questions: formattedQuestions,
        answers: formattedAnswers
      });
      
      const response = await fetch('/api/generate-video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          topic: quiz.topic,
          questions: formattedQuestions,
          answers: formattedAnswers
        }),
      });
      
      const data = await response.json();
      console.log('Video generation response:', data);
      
      if (!response.ok) {
        throw new Error(data.error || 'Failed to generate video');
      }
      
      // If the response indicates all answers are correct, handle it gracefully
      if (data.message && data.message.includes('All answers are correct')) {
        setVideoError('Great job! All answers are correct. No video needed.');
        return;
      }
      
      // Handle different possible response formats
      if (data.videos && Array.isArray(data.videos) && data.videos.length > 0) {
        // New format: { videos: [{ url: string, type: string }] }
        const video = data.videos[0];
        if (video && video.url) {
          setVideoUrl(video.url);
          return;
        }
      }
      
      // Fallback formats for backward compatibility
      if (data.videoUrl || data.video_url) {
        setVideoUrl(data.videoUrl || data.video_url);
        return;
      }
      
      // If we get here, no valid video URL was found
      console.error('No video URL found in response:', data);
      throw new Error('No video URL was provided in the response. Please try again or contact support if the issue persists.');
    } catch (err) {
      console.error('Error generating video:', err);
      setVideoError(err instanceof Error ? err.message : 'Failed to generate video');
    } finally {
      setIsGeneratingVideo(false);
    }
  };

  const handleAnswer = useCallback((questionId: string, answer: string) => {
    setAnswers(prev => ({
      ...prev,
      [questionId]: answer
    }));
  }, []);

  const submitQuiz = useCallback(async () => {
    if (!quiz) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      // Convert answers from {questionId: answer} to array of answers in order
      const answerArray = quiz.questions.map(question => answers[question.id] || '');
      
      // Format questions for the backend
      const formattedQuestions = quiz.questions.map(q => ({
        q: q.question,
        a: q.correctAnswer, // The backend expects 'a' for correct answer
        opts: Object.entries(q.options).map(([key, value]) => `${key}) ${value}`),
        explanation: q.explanation || ''
      }));
      
      const response = await fetch('/api/grade_quiz', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          answers: answerArray, 
          questions: formattedQuestions 
        }),
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to grade quiz');
      }
      
      const data = await response.json();
      console.log('Quiz grading response:', data);
      
      // Handle different response formats
      if (data.wrong_answers !== undefined) {
        // New format with wrong_answers count
        setResult({
          score: data.score,
          total: data.total || 3, // Default to 3 if not provided
          wrongAnswers: data.wrong_answers === 0 ? [] : [
            // If there are wrong answers but no details, create a generic message
            {
              question: 'Some questions were answered incorrectly',
              userAnswer: 'Incorrect',
              correctAnswer: 'Correct',
              explanation: 'Please review the material and try again.'
            }
          ]
        });
      } else if (data.wrong_questions) {
        // Old format with detailed wrong questions
        setResult({
          score: data.score,
          total: data.total_questions,
          wrongAnswers: data.wrong_questions.map((wq: any) => ({
            question: wq.question,
            userAnswer: wq.user_answer_text || wq.user_answer,
            correctAnswer: wq.correct_answer_text || wq.correct_answer,
            explanation: wq.explanation || '',
          })),
        });
      } else {
        // Fallback for any other format
        setResult({
          score: 0,
          total: 3,
          wrongAnswers: [{
            question: 'Error processing results',
            userAnswer: 'Error',
            correctAnswer: 'Unknown',
            explanation: 'There was an issue processing your quiz results.'
          }]
        });
      }
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to grade quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [answers, quiz]);

  // Show loading state when not on client or when loading data
  if (!isClient || isLoading) {
    return <LoadingState />;
  }

  // Show loading state when not on client or when loading data
  if (!isClient || isLoading) {
    return <LoadingState />;
  }

  // Redirect to signin if not authenticated
  if (!isAuthenticated) {
    router.push('/auth/signin');
    return <LoadingState />;
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      {!quiz ? (
        <div className="max-w-2xl mx-auto bg-white rounded-lg shadow-md p-6">
          <h1 className="text-2xl font-bold text-gray-800 mb-6">Create a personalised tutor for me</h1>
          {error && (
            <div className="mb-4 p-4 bg-red-50 text-red-700 rounded-md">
              {error}
            </div>
          )}
          <div className="mb-6">
            <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-2">
              Enter a topic you would like to be assessed on:
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                id="topic"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g., Jazz Music, Ancient Rome, World History"
                className="flex-1 px-4 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
              />
              <button
                onClick={generateQuiz}
                disabled={!topic.trim() || isLoading}
                className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Generating...' : 'Start Assessment'}
              </button>
            </div>
          </div>
        </div>
      ) : !result ? (
        <div className="max-w-3xl mx-auto bg-white rounded-lg shadow-md overflow-hidden">
          <div className="p-6 border-b border-gray-200">
            <h1 className="text-2xl font-bold text-gray-800">Quiz: {quiz.topic}</h1>
          </div>
          
          {error && (
            <div className="bg-red-50 text-red-700 p-4">
              {error}
            </div>
          )}
          
          <div className="divide-y divide-gray-200">
            {quiz.questions.map((question, index) => {
              // Ensure question has an id, fallback to index if not
              const questionKey = question.id || `question-${index}`;
              
              return (
                <div key={questionKey} className="p-6">
                  <h3 className="text-lg font-medium text-gray-900 mb-4">
                    {index + 1}. {question.question}
                  </h3>
                  
                  <div className="space-y-3">
                    {(() => {
                      console.log(`Rendering options for question ${questionKey}:`, question.options);
                      
                      // Handle case where options is an array
                      if (Array.isArray(question.options)) {
                        console.log('Options is an array, mapping with indices');
                        return question.options.map((option: string, idx: number) => {
                          const optionKey = `option-${idx}`;
                          const inputId = `${questionKey}-${optionKey}`;
                          
                          return (
                            <div key={inputId} className="flex items-center">
                              <input
                                id={inputId}
                                name={`question-${questionKey}`}
                                type="radio"
                                checked={answers[questionKey] === optionKey}
                                onChange={() => handleAnswer(questionKey, optionKey)}
                                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                              />
                              <label 
                                htmlFor={inputId}
                                className="ml-3 block text-gray-700"
                              >
                                {option}
                              </label>
                            </div>
                          );
                        });
                      }
                      
                      // Handle case where options is an object
                      if (question.options && typeof question.options === 'object') {
                        console.log('Options is an object, mapping entries');
                        return Object.entries(question.options).map(([key, value]) => {
                          const optionKey = key || `option-${Object.keys(question.options).indexOf(key)}`;
                          const inputId = `${questionKey}-${optionKey}`;
                          
                          return (
                            <div key={inputId} className="flex items-center">
                              <input
                                id={inputId}
                                name={`question-${questionKey}`}
                                type="radio"
                                checked={answers[questionKey] === key}
                                onChange={() => handleAnswer(questionKey, key)}
                                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                              />
                              <label 
                                htmlFor={inputId}
                                className="ml-3 block text-gray-700"
                              >
                                {String(value)}
                              </label>
                            </div>
                          );
                        });
                      }
                      
                      // Fallback if options is not in expected format
                      console.warn('Unexpected options format:', question.options);
                      return (
                        <div className="text-red-500">
                          Error: Could not display options for this question.
                        </div>
                      );
                    })()}
                  </div>
                </div>
              );
            })}
          </div>
          
          <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex justify-end">
            <button
              onClick={submitQuiz}
              disabled={Object.keys(answers).length < quiz.questions.length || isLoading}
              className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? 'Submitting...' : 'Submit Quiz'}
            </button>
          </div>
        </div>
      ) : (
        <div className="max-w-3xl mx-auto">
          <div className="bg-white rounded-lg shadow-md overflow-hidden mb-8">
            <div className="p-6 bg-gradient-to-r from-blue-600 to-blue-700 text-white">
              <h1 className="text-2xl font-bold">Quiz Results</h1>
              <p className="mt-2 opacity-90">
                You scored {result.score} out of {result.total}&#33;
              </p>
            </div>
            
            <div className="p-6">
              {result.wrongAnswers.length > 0 ? (
                <div>
                  <div className="flex justify-between items-center mb-6">
                    <h2 className="text-lg font-medium text-gray-900">
                      Areas for Improvement
                    </h2>
                    <button
                      onClick={generateVideo}
                      disabled={isGeneratingVideo}
                      className={`px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 ${isGeneratingVideo ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {isGeneratingVideo ? 'Generating...' : 'Generate Video'}
                    </button>
                  </div>
                  <div className="space-y-3">
                    {result.wrongAnswers.map((wrong, index) => (
                      <div 
                        key={`wrong-${index}`} 
                        className="flex items-center p-3 bg-gray-50 rounded-md border border-gray-200"
                      >
                        <div className="flex-shrink-0 h-5 w-5 text-red-500">
                          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
                          </svg>
                        </div>
                        <p className="ml-3 text-sm font-medium text-gray-700">
                          {wrong.question}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-center py-8">
                  <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100">
                    <svg className="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <h3 className="mt-3 text-lg font-medium text-gray-900">Perfect Score!</h3>
                  <p className="mt-2 text-sm text-gray-500">You got all the questions right. Great job!</p>
                  <div className="mt-6">
                    <button
                      onClick={generateVideo}
                      disabled={isGeneratingVideo}
                      className={`inline-flex items-center px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 ${isGeneratingVideo ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      <svg className="-ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {isGeneratingVideo ? 'Generating Video...' : 'Generate Video'}
                    </button>
                    {videoError && (
                      <div className="mt-2 text-sm text-red-600">
                        {videoError}
                      </div>
                    )}
                    {videoUrl && (
                      <div className="mt-4">
                        <p className="text-sm text-green-600 mb-2">Video generated successfully!</p>
                        <a 
                          href={videoUrl} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline text-sm"
                        >
                          Watch Video
                        </a>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function QuizPage() {
  const { user, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading || !isAuthenticated) {
    return <LoadingState />;
  }

  return <QuizPageContent />;
}
