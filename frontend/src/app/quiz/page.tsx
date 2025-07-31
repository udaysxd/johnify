'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import VideoPlayer from '@/components/VideoPlayer';
import Header from '@/components/Header';

export default function QuizPage() {
  const { data: session, status } = useSession();
  const [topic, setTopic] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false);
  const [videos, setVideos] = useState<Array<{
    url: string;
    level: number;
    title: string;
  }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [quiz, setQuiz] = useState<any>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [result, setResult] = useState<{
    score: number;
    total: number;
    wrongAnswers: Array<{
      question: string;
      userAnswer: string;
      correctAnswer: string;
      explanation: string;
    }>;
  } | null>(null);
  const router = useRouter();

  // Redirect to login if not authenticated
  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/auth/signin');
    }
  }, [status, router]);

  if (status === 'loading') {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  const startQuiz = async () => {
    if (!topic.trim()) return;
    
    setIsLoading(true);
    try {
      const response = await fetch('/api/quiz', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ topic, numQuestions: 3 }),
      });

      if (!response.ok) {
        throw new Error('Failed to generate quiz');
      }

      const data = await response.json();
      setQuiz(data);
    } catch (error) {
      console.error('Error:', error);
      alert('Failed to generate quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAnswer = (questionIndex: number, answer: string) => {
    setAnswers(prev => ({
      ...prev,
      [questionIndex]: answer
    }));
  };

  const generateVideo = async () => {
    if (!result || isGeneratingVideo) return;
    
    setIsGeneratingVideo(true);
    setVideos([]); // Reset videos when generating new ones
    setError(null); // Clear any previous errors
    try {
      // Prepare answers in the format expected by the backend
      const formattedAnswers: Record<string, string> = {};
      
      // Process answers to ensure they match the backend's expectations
      Object.entries(answers).forEach(([index, answer]) => {
        if (answer !== undefined && answer !== null) {
          formattedAnswers[index] = answer.toString();
        }
      });

      // Prepare questions with string answer indices
      const formattedQuestions = quiz.questions.map((q: any) => ({
        ...q,
        a: q.a.toString(),
        opts: Object.fromEntries(
          Object.entries(q.opts).map(([key, value]) => [key.toString(), value])
        )
      }));

      const response = await fetch('/api/generate-video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          topic,
          questions: formattedQuestions,
          answers: formattedAnswers
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to generate video');
      }

      const data = await response.json();
      console.log('Video generation response:', data);
      
      if (data.videos && Array.isArray(data.videos) && data.videos.length > 0) {
        setVideos(data.videos);
      } else if (data.error) {
        throw new Error(data.details || data.error || 'Failed to generate videos');
      } else {
        throw new Error('No videos were generated. Please try again.');
      }
    } catch (error: any) {
      console.error('Error generating video:', error);
      setError(error.message || 'Failed to generate video. Please try again.');
      
      // If we have a 504 Gateway Timeout, suggest the user to wait
      if (error.message?.includes('504') || error.message?.includes('timeout')) {
        setError('The video generation is taking longer than expected. Your videos are still being processed and will be available shortly.');
      }
    } finally {
      setIsGeneratingVideo(false);
    }
  };

  const submitQuiz = async () => {
    if (!quiz) return;
    
    console.log('Submitting quiz with answers:', answers);
    console.log('Quiz questions:', quiz.questions);
    
    let score = 0;
    const wrongAnswers: Array<{
      question: string;
      userAnswer: string;
      correctAnswer: string;
      explanation: string;
    }> = [];
    
    quiz.questions.forEach((q: any, index: number) => {
      const userAnswerKey = answers[index]?.toString().toLowerCase();
      const correctAnswerKey = q.a?.toString().toLowerCase();
      
      // Get the actual answer text for debugging
      const correctAnswerText = q.opts[correctAnswerKey.toUpperCase()] || 'No correct answer found';
      const userAnswerText = userAnswerKey ? (q.opts[userAnswerKey.toUpperCase()] || 'Invalid answer') : 'No answer';
      
      // Normalize both keys to lowercase for comparison
      const isCorrect = userAnswerKey === correctAnswerKey;
      
      console.log(`Question ${index + 1}:`, {
        question: q.q,
        userAnswerKey,
        userAnswerText,
        correctAnswerKey: correctAnswerKey.toLowerCase(),
        correctAnswerText,
        isCorrect,
        options: q.opts
      });
      
      if (isCorrect) {
        score++;
      } else {
        wrongAnswers.push({
          question: q.q,
          userAnswer: userAnswerText,
          correctAnswer: correctAnswerText,
          explanation: q.explanation || 'No explanation available'
        });
      }
    });
    
    console.log('Final score:', score, 'out of', quiz.questions.length);
    console.log('Wrong answers:', wrongAnswers);

    const result = {
      score,
      total: quiz.questions.length,
      wrongAnswers
    };
    
    setResult(result);
    
    // Only generate video if there are wrong answers
    if (wrongAnswers.length > 0) {
      console.log('Generating video for wrong answers...');
      await generateVideo();
    } else {
      console.log('All answers correct! No video needed.');
    }
  };

  // Check video accessibility when videos change
  useEffect(() => {
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
  }, [videos]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Hang on! Let's assess where you stand today on the {topic}...</p>
        </div>
      </div>
    );
  }

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
                  {result.wrongAnswers.map((wrong: any, index: number) => (
                    <li key={index} className="flex items-start">
                      <span className="text-red-500 mr-2">•</span>
                      <span>{wrong.question}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="mb-6 p-4 bg-green-50 text-green-700 rounded-md">
                <p className="font-medium">🎉 Perfect score! You've mastered this topic.</p>
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
              
              <a
                href="/"
                className="flex-1 text-center bg-white border border-gray-300 text-gray-700 py-2 px-4 rounded-md hover:bg-gray-50 transition"
              >
                Back to Home
              </a>
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
              
              <div className="mt-4 text-sm text-gray-600">
                <p className="font-medium mb-2">How to use these videos:</p>
                <ul className="list-disc pl-5 space-y-1">
                  <li>Start with Level 1 for a basic introduction</li>
                  <li>Progress through levels as you understand each concept</li>
                  <li>Use the highest level for a comprehensive review</li>
                </ul>
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
            {quiz.questions.map((q: any, index: number) => (
              <div key={index} className="bg-white p-6 rounded-lg shadow">
                <h3 className="text-lg font-medium mb-4">
                  {index + 1}. {q.q}
                </h3>
                <div className="space-y-2">
                  {Object.entries(q.opts).map(([key, value]) => (
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
          <h1 className="text-2xl font-bold text-center mb-6">What would you like to learn today?</h1>
          
          <div className="mb-6">
            <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-1">
              Enter a topic:
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
            disabled={!topic.trim()}
            className={`w-full bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 transition ${
              !topic.trim() ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            Start Learning
          </button>
        </div>
      </div>
    </div>
  );
}