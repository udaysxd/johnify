"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

export type VideoModalProps = {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  videoUrl: string;
  createdAt?: string;
  creatorName?: string | null;
  showMeta?: boolean; // show title/creator/time section below player
  maxWidthClass?: string; // e.g., "max-w-3xl" | "max-w-4xl"
  postId?: string; // needed for comments
  videoType?: string; // 'ugc' for user uploaded, others for AI generated
};

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const now = Date.now();
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "";
  const diff = Math.max(0, now - then);
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec || 1} second${sec === 1 ? "" : "s"} ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} minute${min === 1 ? "" : "s"} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? "" : "s"} ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} day${day === 1 ? "" : "s"} ago`;
  const mon = Math.floor(day / 30);
  if (mon < 12) return `${mon} month${mon === 1 ? "" : "s"} ago`;
  const yr = Math.floor(day / 365);
  return `${yr} year${yr === 1 ? "" : "s"} ago`;
}

export default function VideoModal({
  isOpen,
  onClose,
  title,
  videoUrl,
  createdAt,
  creatorName,
  showMeta = true,
  maxWidthClass = "max-w-3xl",
  postId,
  videoType,
}: VideoModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const [comments, setComments] = useState<Array<{ comment_id: number; user_id: number; user_name?: string | null; profile_pic_url?: string | null; text: string; created_at?: string | null; likes: number; my_like: boolean; parent_comment_id?: number | null }>>([]);
  const [loadingC, setLoadingC] = useState(false);
  const [errorC, setErrorC] = useState<string | null>(null);
  const [newComment, setNewComment] = useState("");
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [expandedReplies, setExpandedReplies] = useState<Set<number>>(new Set());
  const { user } = useAuth();

  // Close on outside click and lock body scroll
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        onClose();
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.body.style.overflow = "auto";
    };
  }, [isOpen, onClose]);

  async function deleteComment(id: number) {
    try {
      const r = await fetch(`/api/videos/comments/${id}`, { method: 'DELETE', credentials: 'include' });
      if (!r.ok) throw new Error('Failed to delete comment');
      // Refresh to reflect cascaded deletions
      if (postId) {
        const rr = await fetch(`/api/videos/${encodeURIComponent(postId)}/comments`, { cache: 'no-store' });
        if (rr.ok) {
          const data = await rr.json();
          setComments(Array.isArray(data) ? data : []);
        }
      }
    } catch (e) {
      setErrorC(e instanceof Error ? e.message : 'Failed to delete comment');
    }
  }

  // Build threaded structure: top-level + replies
  const threads = useMemo(() => {
    const byParent: Record<string, Array<typeof comments[number]>> = {};
    for (const c of comments) {
      const key = String(c.parent_comment_id ?? 'root');
      if (!byParent[key]) byParent[key] = [];
      byParent[key].push(c);
    }
    const roots = byParent['root'] || [];
    const repliesOf = (parentId: number) => byParent[String(parentId)] || [];
    return { roots, repliesOf };
  }, [comments]);

  function toggleReplies(commentId: number) {
    setExpandedReplies((prev) => {
      const next = new Set(prev);
      if (next.has(commentId)) next.delete(commentId); else next.add(commentId);
      return next;
    });
  }

  function CommentItem({ c, depth = 0 }: { c: (typeof comments)[number]; depth?: number }) {
    const canDelete = user && String(user.user_id) === String(c.user_id);
    return (
      <li className="p-3 flex items-start gap-3">
        {c.profile_pic_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={c.profile_pic_url} alt={c.user_name || ''} className="h-7 w-7 rounded-full object-cover border border-gray-200" />
        ) : (
          <div className="h-7 w-7 rounded-full bg-gray-200" />)
        }
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <div className="truncate text-sm font-medium text-gray-900">{c.user_name || 'User'}</div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => toggleLikeComment(c)}
                className={`text-xs flex items-center gap-1 ${c.my_like ? 'text-red-600' : 'text-gray-500 hover:text-gray-700'}`}
                aria-pressed={c.my_like}
              >
                {c.my_like ? (
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4"><path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.462 2.25 9.003 2.25 6.387 4.357 4.5 6.75 4.5c1.503 0 2.86.654 3.75 1.68A5.123 5.123 0 0114.25 4.5c2.393 0 4.5 1.887 4.5 4.503 0 3.46-2.438 6.358-4.739 8.504a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.218l-.022.012-.007.003a.75.75 0 01-.645 0z" /></svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 8.25c0-2.485-2.015-4.5-4.5-4.5-1.86 0-3.456 1.116-4.125 2.709-.669-1.593-2.265-2.709-4.125-2.709C5.015 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" /></svg>
                )}
                <span>{c.likes}</span>
              </button>
              <button onClick={() => setReplyTo(c.comment_id)} className="text-xs text-gray-500 hover:text-gray-700">Reply</button>
              {canDelete ? (
                <button onClick={() => deleteComment(c.comment_id)} className="text-xs text-gray-500 hover:text-gray-700">Delete</button>
              ) : null}
            </div>
          </div>
          <p className="text-sm text-gray-800 break-words whitespace-pre-wrap">{c.text}</p>
          {c.created_at ? <p className="text-xs text-gray-500">{timeAgo(c.created_at)}</p> : null}
          {/* Replies */}
          {(() => {
            const replies = threads.repliesOf(c.comment_id);
            if (replies.length === 0) return null;
            const expanded = expandedReplies.has(c.comment_id);
            return (
              <div className="mt-2 ml-6">
                {!expanded ? (
                  <button
                    type="button"
                    onClick={() => toggleReplies(c.comment_id)}
                    className="text-xs text-gray-500 hover:text-gray-700"
                  >
                    View {replies.length} repl{replies.length === 1 ? 'y' : 'ies'}
                  </button>
                ) : (
                  <ul className="mt-2 border-l border-gray-200">
                    {replies.map((child) => (
                      <CommentItem key={child.comment_id} c={child} depth={depth + 1} />
                    ))}
                    <li className="mt-2">
                      <button
                        type="button"
                        onClick={() => toggleReplies(c.comment_id)}
                        className="text-xs text-gray-500 hover:text-gray-700"
                      >
                        Hide repl{replies.length === 1 ? 'y' : 'ies'}
                      </button>
                    </li>
                  </ul>
                )}
              </div>
            );
          })()}
        </div>
      </li>
    );
  }

  // Attempt autoplay when opened (only for actual videos)
  useEffect(() => {
    if (!isOpen || !videoRef.current || !videoUrl) return;
    try {
      // Reload to ensure fresh source
      videoRef.current.load();
    } catch {}
    setTimeout(async () => {
      try {
        await videoRef.current?.play();
      } catch {}
    }, 0);
  }, [isOpen, videoUrl]);

  // Load comments when opened and postId present (only for actual videos)
  useEffect(() => {
    if (!isOpen || !postId || !videoUrl) return;
    let active = true;
    (async () => {
      try {
        setLoadingC(true);
        setErrorC(null);
        const r = await fetch(`/api/videos/${encodeURIComponent(postId)}/comments`, { cache: 'no-store' });
        if (!r.ok) throw new Error(`Failed to load comments (${r.status})`);
        const data = await r.json();
        if (active) setComments(Array.isArray(data) ? data : []);
      } catch (e) {
        if (active) setErrorC(e instanceof Error ? e.message : 'Failed to load comments');
      } finally {
        if (active) setLoadingC(false);
      }
    })();
    return () => { active = false; };
  }, [isOpen, postId, videoUrl]);

  // Reset comment state when opening processing videos
  useEffect(() => {
    if (isOpen && !videoUrl) {
      setComments([]);
      setLoadingC(false);
      setErrorC(null);
      setNewComment("");
      setReplyTo(null);
    }
  }, [isOpen, videoUrl]);

  async function submitComment(e: React.FormEvent) {
    e.preventDefault();
    if (!postId || !videoUrl) return; // Don't allow comments on processing videos
    const text = newComment.trim();
    if (!text) return;
    try {
      const r = await fetch(`/api/videos/${encodeURIComponent(postId)}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ text, parent_comment_id: replyTo }),
      });
      if (!r.ok) throw new Error('Failed to add comment');
      const c = await r.json();
      setComments((prev) => [...prev, c]);
      setNewComment("");
      setReplyTo(null);
    } catch (e) {
      setErrorC(e instanceof Error ? e.message : 'Failed to add comment');
    }
  }

  async function toggleLikeComment(cmt: { comment_id: number; my_like: boolean }) {
    try {
      // optimistic
      setComments((prev) => prev.map((c) => c.comment_id === cmt.comment_id ? { ...c, my_like: !c.my_like, likes: c.my_like ? Math.max(0, c.likes - 1) : c.likes + 1 } : c));
      if (cmt.my_like) {
        const r = await fetch(`/api/videos/comments/${cmt.comment_id}/like`, { method: 'DELETE', credentials: 'include' });
        if (!r.ok) throw new Error('Failed to unlike');
        const data = await r.json().catch(() => ({}));
        setComments((prev) => prev.map((c) => c.comment_id === cmt.comment_id ? { ...c, likes: typeof data.likes === 'number' ? data.likes : c.likes, my_like: false } : c));
      } else {
        const r = await fetch(`/api/videos/comments/${cmt.comment_id}/like`, { method: 'PUT', credentials: 'include' });
        if (!r.ok) throw new Error('Failed to like');
        const data = await r.json().catch(() => ({}));
        setComments((prev) => prev.map((c) => c.comment_id === cmt.comment_id ? { ...c, likes: typeof data.likes === 'number' ? data.likes : c.likes, my_like: true } : c));
      }
    } catch (e) {
      // reload comments on error
      try {
        if (postId) {
          const r = await fetch(`/api/videos/${encodeURIComponent(postId)}/comments`, { cache: 'no-store' });
          if (r.ok) {
            const data = await r.json();
            setComments(Array.isArray(data) ? data : []);
          }
        }
      } catch {}
    }
  }

  if (!isOpen) return null;

  const proxySrc = videoUrl ? `/api/proxy-video?url=${encodeURIComponent(videoUrl)}` : '';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      {/* Modal content */}
      <div ref={modalRef} className={`relative z-10 w-full ${maxWidthClass} mx-4 bg-white rounded-lg shadow-lg overflow-hidden`}>
        <div className="relative pt-[56.25%] bg-black">
          {!videoUrl ? (
            // Processing video placeholder
            <div className="absolute inset-0 flex items-center justify-center bg-gray-900 text-white">
              <div className="text-center">
                <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-white mx-auto mb-4"></div>
                <h3 className="text-lg font-semibold mb-2">Video Processing</h3>
                <p className="text-gray-300">This video is still being processed. Please check back later.</p>
              </div>
            </div>
          ) : (
            // Actual video player
            <video
              ref={videoRef}
              className="absolute top-0 left-0 w-full h-full"
              controls
              autoPlay
              crossOrigin="anonymous"
              playsInline
              preload="auto"
              src={proxySrc}
              onEnded={() => videoRef.current?.pause()}
              onLoadedMetadata={() => {
                videoRef.current?.play().catch(() => {});
              }}
              onError={() => {
                const v = videoRef.current;
                const err = v?.error;
                console.error("Video error event", {
                  src: proxySrc,
                  networkState: v?.networkState,
                  readyState: v?.readyState,
                  errorCode: err?.code,
                  errorMessage: err?.message,
                });
              }}
            >
              <source src={proxySrc} type="video/mp4" />
              Your browser does not support the video tag.
            </video>
          )}
          <button
            onClick={onClose}
            className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
            aria-label="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {showMeta && (
          <div className="p-6">
            {title ? <h2 className="text-2xl font-bold text-gray-900">{title}</h2> : null}
            {creatorName ? <p className="mt-2 text-gray-800 font-medium">{creatorName}</p> : null}
            {createdAt ? <p className="mt-1 text-gray-600">{timeAgo(createdAt)}</p> : null}

            {/* Comments - only for actual videos */}
            {postId && videoUrl ? (
              <div className="mt-6">
                <h3 className="text-base font-semibold text-gray-900 mb-3">Comments</h3>
                {errorC && <div className="text-red-600 text-sm mb-2">{errorC}</div>}
                <div className="max-h-64 overflow-y-auto border border-gray-200 rounded">
                  {loadingC ? (
                    <div className="p-3 text-sm text-gray-600">Loading…</div>
                  ) : comments.length === 0 ? (
                    <div className="p-3 text-sm text-gray-600">No comments yet. Be the first!</div>
                  ) : (
                    <ul className="divide-y divide-gray-200">
                      {threads.roots.map((root) => (
                        <CommentItem key={root.comment_id} c={root} />
                      ))}
                    </ul>
                  )}
                </div>
                {replyTo !== null ? (
                  <div className="mt-2 text-xs text-gray-600 flex items-center gap-2">
                    Replying to comment #{replyTo}
                    <button type="button" className="text-blue-600" onClick={() => setReplyTo(null)}>Cancel</button>
                  </div>
                ) : null}
                <form onSubmit={submitComment} className="mt-2 flex items-center gap-2">
                  <input
                    type="text"
                    className="flex-1 px-3 py-2 rounded border border-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder={replyTo ? "Reply..." : "Add a comment..."}
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    maxLength={500}
                  />
                  <button type="submit" className="btn-primary px-3 py-2 text-sm">Post</button>
                </form>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
