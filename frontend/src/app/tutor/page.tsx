'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import LoadingState from '@/components/LoadingState';

// Define types
interface QuizQuestion {
  id: string;
  question: string;
  correctAnswer: string;
  options: Record<string, string> | string[];
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
    userAnswer?: string;  // optional to match API variance
    explanation?: string;
  }>;
}

interface ApiQuestion {
  id?: string;
  q: string;
  a: string;
  opts?: Record<string, string> | string[];
  explanation?: string;
}

interface ApiWrongQuestion {
  question: string;
  user_answer_text?: string;
  user_answer?: string;
  correct_answer_text?: string;
  correct_answer: string;
  explanation?: string;
}

function TutorPageContent() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isAuthenticated = !!user;
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [quizTopic, setQuizTopic] = useState('');
  const [quiz, setQuiz] = useState<QuizData | null>(null);
  const [displayTitle, setDisplayTitle] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isClient, setIsClient] = useState(false);
  const [pendingAuto, setPendingAuto] = useState(false);
  const searchParams = useSearchParams();
  const funFacts = [
    'Your brain uses about 20% of your body\'s energy—even at rest.',
    'Learning something new builds fresh neural connections.',
    'Short breaks improve focus and memory retention.',
    'Explaining a topic to others boosts your understanding.',
    'Sleep consolidates memories—review before bedtime!',
    'Curiosity triggers dopamine, enhancing learning.',
  ];
  const [dynamicFunFacts, setDynamicFunFacts] = useState<string[] | null>(null);
  const [factIndex, setFactIndex] = useState(0);

  // Rotate fun facts while generating video
  useEffect(() => {
    if (!isGeneratingVideo) return;
    const currentFacts = dynamicFunFacts && dynamicFunFacts.length > 0 ? dynamicFunFacts : funFacts;
    const id = setInterval(() => {
      setFactIndex((i) => (i + 1) % currentFacts.length);
    }, 6000);
    return () => clearInterval(id);
  }, [isGeneratingVideo, dynamicFunFacts, funFacts.length]);

  useEffect(() => {
    setIsClient(true);
  }, []);

  // Check authentication status when component mounts or auth state changes
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/auth/signin');
    }
  }, [authLoading, isAuthenticated, router]);

  // Prefill topic from URL and optionally autostart
  useEffect(() => {
    if (!isClient) return;
    // Wait until auth status is known; Tutor requires auth
    if (authLoading) return;
    const topic = (searchParams.get('topic') || '').trim();
    const auto = String(searchParams.get('autostart') || '').toLowerCase();
    const shouldAuto = auto === '1' || auto === 'true';
    if (topic && topic !== quizTopic) {
      setQuizTopic(topic);
    }
    if (shouldAuto && topic) {
      setPendingAuto(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, isClient, authLoading]);

  const generateQuiz = useCallback(async () => {
    // Prevent early clicks before auth is ready or if already processing
    if (authLoading || !isAuthenticated || isLoading) return;
    if (!quizTopic.trim()) return;

    setIsLoading(true);
    setError(null);
    setQuiz(null);
    setAnswers({});
    setResult(null);

    try {
      const response = await fetch('/api/tutor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ topic: quizTopic, numQuestions: 3 }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to generate quiz');
      }

      const responseData = await response.json();
      console.log('Raw Tutor API response:', responseData);

      const quizData: QuizData = {
        topic: responseData.topic || 'General Knowledge',
        questions: (responseData.questions as ApiQuestion[] || []).map((q, index) => ({
          id: q.id || `question-${index}`,
          question: q.q || `Question ${index + 1}`,
          correctAnswer: q.a || '',
          options: (q.opts as Record<string, string> | string[] | undefined) ?? {},
          explanation: q.explanation,
        }))
      };

      console.log('Processed tutor quiz data:', JSON.stringify(quizData, null, 2));
      setQuiz(quizData);
      // Wire corrected title (display-only) and dynamic fun facts if provided
      if (responseData.corrected_title && typeof responseData.corrected_title === 'string') {
        try {
          const t = String(responseData.corrected_title).trim().slice(0, 100);
          if (t) setDisplayTitle(t);
        } catch {}
      } else {
        setDisplayTitle(null);
      }
      if (Array.isArray(responseData.fun_facts) && responseData.fun_facts.length > 0) {
        const cleaned = responseData.fun_facts.map((s: unknown) => String(s || '').trim()).filter((s: string) => !!s);
        if (cleaned.length > 0) setDynamicFunFacts(cleaned.slice(0, 10));
        else setDynamicFunFacts(null);
      } else {
        setDynamicFunFacts(null);
      }
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to generate quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [quizTopic, authLoading, isAuthenticated, isLoading]);

  // Fire generate once when pendingAuto is set and prerequisites are ready
  useEffect(() => {
    if (!pendingAuto) return;
    if (authLoading || !isAuthenticated) return;
    if (!quizTopic.trim() || isLoading) return;
    setPendingAuto(false);
    void generateQuiz();
  }, [pendingAuto, authLoading, isAuthenticated, quizTopic, isLoading, generateQuiz]);

  const handleStartSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Call generateQuiz; it already has guards for auth/loading
    void generateQuiz();
  };

  const generateVideo = async () => {
    // Prevent early clicks before auth is ready or if already generating
    if (authLoading || !isAuthenticated || isGeneratingVideo) return;
    if (!quiz) return;

    if (result) {
      if (result.wrongAnswers.length === 0) {
        setVideoError('Great job! All answers are correct. No video needed.');
        return;
        }
    }

    setIsGeneratingVideo(true);
    setVideoError(null);
    setVideoUrl(null);

    try {
      const formattedAnswers: Record<string, string> = {};

      const formattedQuestions = quiz.questions.map((q, index) => {
        const formattedOpts: Record<string, string> = {};
        if (Array.isArray(q.options)) {
          q.options.forEach((value, idx) => {
            const optionKey = String.fromCharCode(65 + idx); // A, B, C, ...
            formattedOpts[optionKey] = String(value);
          });
        } else if (q.options && typeof q.options === 'object') {
          Object.values(q.options).forEach((value, idx) => {
            const optionKey = String.fromCharCode(65 + idx);
            formattedOpts[optionKey] = String(value);
          });
        }

        const answerKey = answers[q.id];
        if (answerKey !== undefined) {
          const parsed = parseInt(answerKey as string, 10);
          if (!isNaN(parsed)) {
            const letterAnswer = String.fromCharCode(97 + parsed);
            formattedAnswers[index] = letterAnswer;
          } else if (typeof answerKey === 'string' && answerKey.length > 0) {
            formattedAnswers[index] = answerKey[0].toLowerCase();
          }
        }

        return {
          q: q.question || 'No question text',
          a: q.correctAnswer || '',
          opts: formattedOpts,
          explanation: q.explanation || `Explanation for question ${index + 1}`,
        };
      });

      console.log('Tutor sending to generate-video API:', {
        topic: displayTitle || quiz.topic,
        questions: formattedQuestions,
        answers: formattedAnswers,
      });

      const response = await fetch('/api/tutor/generate-video', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: displayTitle || quiz.topic, questions: formattedQuestions, answers: formattedAnswers }),
      });

      const initialStatus = response.status;
      const initialRetryAfter = response.headers.get('retry-after');
      const kickoff = await response.json();
      console.log('Tutor video generation kickoff response:', kickoff);

      if (!response.ok) {
        throw new Error(kickoff.error || kickoff.message || 'Failed to start video generation');
      }

      if (kickoff && kickoff.videos && Array.isArray(kickoff.videos) && kickoff.videos.length > 0) {
        const video = kickoff.videos[0];
        if (video && video.url) {
          setVideoUrl(video.url);
          return;
        }
      }
      if (kickoff.videoUrl || kickoff.video_url) {
        setVideoUrl(kickoff.videoUrl || kickoff.video_url);
        return;
      }
      if (kickoff.message && String(kickoff.message).includes('All answers are correct')) {
        setVideoError('Great job! All answers are correct. No video needed.');
        return;
      }

      // If backend accepted but didn't return a job yet, retry kickoff a few times
      if (initialStatus === 202 || String(kickoff?.status).toLowerCase() === 'processing') {
        const maxKickoffRetries = 6;
        let i = 0;
        const baseDelay = initialRetryAfter ? Math.min(60000, parseInt(initialRetryAfter, 10) * 1000 || 2000) : 2000;
        while (i < maxKickoffRetries) {
          i += 1;
          await new Promise((r) => setTimeout(r, Math.min(10000, baseDelay * Math.pow(1.5, i - 1))));
          const reResp = await fetch('/api/tutor/generate-video', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: displayTitle || quiz.topic, questions: formattedQuestions, answers: formattedAnswers }),
            cache: 'no-store',
          });
          const reJson = await reResp.json().catch(() => ({}));
          console.log('Tutor re-kickoff response:', reJson);
          if (reResp.ok) {
            if (reJson && Array.isArray(reJson.videos) && reJson.videos.length > 0 && reJson.videos[0]?.url) {
              setVideoUrl(String(reJson.videos[0].url));
              return;
            }
            const vAlt = reJson.videoUrl || reJson.video_url;
            if (vAlt) {
              setVideoUrl(String(vAlt));
              return;
            }
            if (reJson.job_id || reJson.jobId) {
              kickoff.job_id = reJson.job_id || reJson.jobId;
              break;
            }
          }
        }
      }

      const jobId: string | undefined = kickoff.job_id || kickoff.jobId;
      if (!jobId) {
        throw new Error('No job_id returned from server. Please try again in a minute.');
      }

      let attempt = 0;
      const maxAttempts = 120;
      while (attempt < maxAttempts) {
        attempt += 1;
        const statusRes = await fetch(`/api/tutor/generate-video-status?job_id=${encodeURIComponent(jobId)}`, { cache: 'no-store' });
        const statusData = await statusRes.json();
        console.log('Tutor status poll', { attempt, status: statusData });

        if (!statusRes.ok) {
          throw new Error(statusData?.error || 'Failed to fetch job status');
        }

        const status = statusData.status as string | undefined;
        if (status === 'done') {
          const videos = statusData.videos as Array<{ url?: string }> | undefined;
          if (videos && videos.length && videos[0]?.url) {
            setVideoUrl(String(videos[0].url));
            return;
          }
          const fallbackUrl = statusData.videoUrl || statusData.video_url;
          if (fallbackUrl) {
            setVideoUrl(String(fallbackUrl));
            return;
          }
          throw new Error('Job finished but no video URL was provided.');
        }
        if (status === 'error') {
          throw new Error(statusData?.error || 'Video generation failed');
        }

        const delayMs = Math.min(10000, 500 * Math.pow(2, Math.min(6, attempt - 1)));
        await new Promise((r) => setTimeout(r, delayMs));
      }

      throw new Error('Video generation is taking longer than expected. Please try again later.');
    } catch (err) {
      console.error('Tutor error generating video:', err);
      setVideoError(err instanceof Error ? err.message : 'Failed to generate video');
    } finally {
      setIsGeneratingVideo(false);
    }
  };

  const handleAnswer = (questionId: string, answer: string) => {
    setAnswers(prev => ({ ...prev, [questionId]: answer }));
  };

  const submitQuiz = useCallback(async () => {
    if (!quiz) return;

    setIsLoading(true);
    setError(null);

    try {
      const answerArray = quiz.questions.map(question => answers[question.id] || '');

      const formattedQuestions = quiz.questions.map(q => ({
        q: q.question,
        a: q.correctAnswer,
        opts: Array.isArray(q.options)
          ? q.options.map((value, idx) => `${String.fromCharCode(65 + idx)}) ${value}`)
          : Object.entries(q.options as Record<string, string>).map(([key, value]) => `${key}) ${value}`),
        explanation: q.explanation || ''
      }));

      const response = await fetch('/api/grade_tutor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers: answerArray, questions: formattedQuestions }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Failed to grade quiz');
      }

      const data = await response.json();
      console.log('Tutor grading response:', data);

      if (data.wrong_answers !== undefined) {
        setResult({
          score: data.score,
          total: data.total || 3,
          wrongAnswers: data.wrong_answers === 0 ? [] : [{
            question: 'Some questions were answered incorrectly',
            userAnswer: 'Incorrect',
            correctAnswer: 'Correct',
            explanation: 'Please review the material and try again.'
          }]
        });
      } else if (data.wrong_questions) {
        setResult({
          score: data.score,
          total: data.total_questions,
          wrongAnswers: (data.wrong_questions as ApiWrongQuestion[]).map((wq) => ({
            question: wq.question,
            userAnswer: wq.user_answer_text || wq.user_answer,
            correctAnswer: wq.correct_answer_text || wq.correct_answer,
            explanation: wq.explanation || '',
          })),
        });
      } else {
        setResult({
          score: 0,
          total: 3,
          wrongAnswers: [{
            question: 'Error processing results',
            userAnswer: 'Error',
            correctAnswer: 'Unknown',
            explanation: 'There was an issue processing your results.'
          }]
        });
      }
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to grade quiz. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [quiz, answers, setIsLoading, setError, setResult]);

  useEffect(() => {
    if (result && !isGeneratingVideo && !videoUrl) {
      generateVideo();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  if (!isClient || isLoading) {
    return <LoadingState />;
  }

  if (!isAuthenticated) {
    router.push('/auth/signin');
    return <LoadingState />;
  }

  return (
    <div className="min-h-screen bg-[var(--color-background)]">
      <div className="py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
      {!quiz ? (
        <div className="bg-white shadow rounded-lg p-6">
          <div className="text-center mb-6">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">Personal Tutor</h1>
            <p className="text-gray-600">Let&apos;s do a short assessment first</p>
          </div>
          {error && (
            <div className="mb-4 p-4 bg-red-50 text-red-700 rounded-md">{error}</div>
          )}
          <form onSubmit={handleStartSubmit} className="space-y-3">
            <div className="mb-2">
              <label htmlFor="topic" className="block text-sm font-medium text-gray-700 mb-1">
                What topic would you like to be assessed on?
              </label>
              <input
                type="text"
                id="topic"
                value={quizTopic}
                onChange={(e) => setQuizTopic(e.target.value)}
                placeholder="e.g., Jazz Music, Ancient Rome, World History"
                className="w-full px-4 py-2 border border-gray-300 rounded-md shadow-sm focus:ring-2 focus:ring-[var(--color-secondary)] focus:border-[var(--color-secondary)]"
                disabled={isLoading}
              />
            </div>
            <div>
              <button
                type="submit"
                disabled={authLoading || !isAuthenticated || !quizTopic.trim() || isLoading}
                className={`w-full flex justify-center py-3 px-4 rounded-md shadow-sm text-sm font-medium btn-primary ${
                  authLoading || !isAuthenticated || !quizTopic.trim() || isLoading ? 'opacity-50 cursor-not-allowed' : ''
                }`}
              >
                {isLoading ? 'Generating Assessment...' : 'Start Assessment'}
              </button>
            </div>
          </form>
        </div>
      ) : !result ? (
        <div className="bg-white shadow rounded-lg overflow-hidden">
          <div className="p-6 border-b border-gray-200 text-center">
            <h1 className="text-2xl font-bold text-gray-800">Tutor Quiz: {displayTitle || quiz.topic}</h1>
            <p className="text-gray-600 mt-1">Answer the questions to unlock your personalised video</p>
          </div>

          {error && <div className="bg-red-50 text-red-700 p-4">{error}</div>}

          <div className="divide-y divide-gray-200">
            {quiz.questions.map((question, index) => {
              const questionKey = question.id || `question-${index}`;
              return (
                <div key={questionKey} className="p-6">
                  <h3 className="text-lg font-medium text-gray-900 mb-4">
                    {index + 1}. {question.question}
                  </h3>

                  <div className="space-y-3">
                    {(() => {
                      // Array options
                      if (Array.isArray(question.options)) {
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
                                className="h-4 w-4 text-[var(--color-secondary)] focus:ring-[var(--color-secondary)] border-gray-300"
                              />
                              <label htmlFor={inputId} className="ml-3 block text-gray-700">
                                {option}
                              </label>
                            </div>
                          );
                        });
                      }
                      // Object options
                      if (question.options && typeof question.options === 'object') {
                        return Object.entries(question.options as Record<string, string>).map(([key, value]) => {
                          const inputId = `${questionKey}-${key}`;
                          return (
                            <div key={inputId} className="flex items-center">
                              <input
                                id={inputId}
                                name={`question-${questionKey}`}
                                type="radio"
                                checked={answers[questionKey] === key}
                                onChange={() => handleAnswer(questionKey, key)}
                                className="h-4 w-4 text-[var(--color-secondary)] focus:ring-[var(--color-secondary)] border-gray-300"
                              />
                              <label htmlFor={inputId} className="ml-3 block text-gray-700">
                                {String(value)}
                              </label>
                            </div>
                          );
                        });
                      }

                      return (
                        <div className="text-red-500">Error: Could not display options for this question.</div>
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
              disabled={authLoading || !isAuthenticated || Object.keys(answers).length < quiz.questions.length || isLoading}
              className={`px-6 py-2 font-medium rounded-md btn-primary ${
                authLoading || !isAuthenticated || Object.keys(answers).length < quiz.questions.length || isLoading ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {isLoading ? 'Submitting...' : 'Submit Quiz'}
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="bg-white rounded-lg shadow overflow-hidden mb-8">
            <div className="p-6 border-b border-gray-200 text-center">
              <h1 className="text-2xl font-bold text-gray-900">Tutor Results</h1>
              <p className="mt-2 text-gray-700">You scored {result!.score} out of {result!.total}!</p>
            </div>
            <div className="p-6">
              {result!.wrongAnswers.length > 0 ? (
                <div>
                  <div className="flex justify-between items-center mb-6">
                    <h2 className="text-lg font-medium text-gray-900">Areas for Improvement</h2>
                    <button
                      onClick={generateVideo}
                      disabled={authLoading || !isAuthenticated || isGeneratingVideo}
                      className={`px-4 py-2 text-sm font-medium rounded-md btn-primary ${isGeneratingVideo ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      {isGeneratingVideo ? 'Generating...' : 'Generate Video'}
                    </button>
                  </div>
                  <div className="space-y-3">
                    {result!.wrongAnswers.map((wrong: { question: string; userAnswer?: string; correctAnswer: string; explanation?: string; }, index: number) => (
                      <div key={`wrong-${index}`} className="p-4 bg-gray-50 rounded-md border border-gray-200">
                        <div className="flex items-start">
                          <div className="flex-shrink-0 h-5 w-5 text-red-500 mt-0.5">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
                            </svg>
                          </div>
                          <div className="ml-3 text-sm text-gray-700">
                            <p className="font-medium">{wrong.question}</p>
                            {wrong.userAnswer && (
                              <p className="mt-1"><span className="font-semibold">Your answer:</span> {wrong.userAnswer}</p>
                            )}
                            {wrong.correctAnswer && (
                              <p className="mt-0.5"><span className="font-semibold">Correct answer:</span> {wrong.correctAnswer}</p>
                            )}
                            {wrong.explanation && (
                              <p className="mt-0.5 text-gray-600"><span className="font-semibold">Explanation:</span> {wrong.explanation}</p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {videoError && <div className="mt-4 p-3 bg-red-50 text-red-700 rounded-md text-sm">{videoError}</div>}
                  {isGeneratingVideo && (
                    <div className="mt-6 p-4 rounded-lg border border-yellow-300 bg-[#f7b801]/15">
                      <div className="flex items-center justify-center gap-2 mb-2">
                        <svg className="h-5 w-5 text-[#f7b801]" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                          <path d="M11 3a7 7 0 00-4.546 12.316c.3.26.546.585.71.953l.087.205c.177.415.597.676 1.05.676h3.398a1.2 1.2 0 001.097-.676l.087-.205c.164-.368.41-.693.71-.953A7 7 0 0011 3zm-1 14a1 1 0 102 0h-2z" />
                        </svg>
                        <h3 className="text-md font-semibold text-gray-900">Some fun facts…</h3>
                      </div>
                      <div className="min-h-[56px] flex items-center justify-center text-gray-900 font-semibold text-base text-center px-4 transition-all">
                        {(dynamicFunFacts && dynamicFunFacts.length > 0 ? dynamicFunFacts : funFacts)[factIndex]}
                      </div>
                      <div className="mt-2 flex justify-center gap-1">
                        {(dynamicFunFacts && dynamicFunFacts.length > 0 ? dynamicFunFacts : funFacts).map((_, i) => (
                          <span key={i} className={`h-1.5 w-1.5 rounded-full ${i === factIndex ? 'bg-[#f7b801]' : 'bg-gray-300'}`}></span>
                        ))}
                      </div>
                    </div>
                  )}
                  {videoUrl && (
                    <div className="mt-6">
                      <h3 className="text-md font-semibold mb-2">Your Video</h3>
                      <div className="aspect-w-16 aspect-h-9 bg-black rounded-lg overflow-hidden">
                        <video src={videoUrl} controls className="w-full h-full" autoPlay>
                          Your browser does not support the video tag.
                        </video>
                      </div>
                    </div>
                  )}
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
                      disabled={authLoading || !isAuthenticated || isGeneratingVideo}
                      className={`inline-flex items-center px-4 py-2 text-sm font-medium rounded-md btn-primary ${isGeneratingVideo ? 'opacity-50 cursor-not-allowed' : ''}`}
                    >
                      <svg className="-ml-1 mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {isGeneratingVideo ? 'Generating Video...' : 'Generate Video'}
                    </button>
                    {videoError && <div className="mt-2 p-3 bg-red-50 text-red-700 rounded-md text-sm">{videoError}</div>}
                    {isGeneratingVideo && (
                      <div className="mt-4 p-4 rounded-lg border border-yellow-300 bg-[#f7b801]/15">
                        <div className="flex items-center justify-center gap-2 mb-2">
                          <svg className="h-5 w-5 text-[#f7b801]" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                            <path d="M11 3a7 7 0 00-4.546 12.316c.3.26.546.585.71.953l.087.205c.177.415.597.676 1.05.676h3.398a1.2 1.2 0 001.097-.676l.087-.205c.164-.368.41-.693.71-.953A7 7 0 0011 3zm-1 14a1 1 0 102 0h-2z" />
                          </svg>
                          <h3 className="text-md font-semibold text-gray-900">Some fun facts…</h3>
                        </div>
                        <div className="min-h-[56px] flex items-center justify-center text-gray-900 font-semibold text-base text-center px-4 transition-all">
                          {(dynamicFunFacts && dynamicFunFacts.length > 0 ? dynamicFunFacts : funFacts)[factIndex]}
                        </div>
                        <div className="mt-2 flex justify-center gap-1">
                          {(dynamicFunFacts && dynamicFunFacts.length > 0 ? dynamicFunFacts : funFacts).map((_, i) => (
                            <span key={i} className={`h-1.5 w-1.5 rounded-full ${i === factIndex ? 'bg-[#f7b801]' : 'bg-gray-300'}`}></span>
                          ))}
                        </div>
                      </div>
                    )}
                    {videoUrl && (
                      <div className="mt-6">
                        <h3 className="text-md font-semibold mb-2">Your Video</h3>
                        <div className="aspect-w-16 aspect-h-9 bg-black rounded-lg overflow-hidden">
                          <video src={videoUrl} controls className="w-full h-full" autoPlay>
                            Your browser does not support the video tag.
                          </video>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
        <div className="mt-8 text-center text-sm text-gray-500">
          <p>Note: Video generation may take a few moments. Please be patient.</p>
        </div>
      </div>
    </div>
    </div>
  );
}

export default function TutorPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const isAuthenticated = !!user;

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push('/auth/signin');
    }
  }, [isAuthenticated, loading, router]);

  if (loading || !isAuthenticated) {
    return <LoadingState />;
  }

  return <TutorPageContent />;
}
