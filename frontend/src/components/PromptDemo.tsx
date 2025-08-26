"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function PromptDemo() {
  const [value, setValue] = useState("");
  const max = 500;
  const count = value.length;
  const router = useRouter();

  const onLearn = () => {
    const topic = value.trim();
    if (!topic) return;
    const url = `/tutor?topic=${encodeURIComponent(topic)}&autostart=1`;
    router.push(url);
  };

  return (
    <div className="w-full">
      <label htmlFor="prompt" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
        Learn anything
      </label>
      <textarea
        id="prompt"
        value={value}
        onChange={(e) => setValue(e.target.value.slice(0, max))}
        maxLength={max}
        rows={5}
        placeholder="Write the topic for which you need a tutor..."
        className="w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 p-4 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
      <div className="mt-2 flex items-center justify-between">
        <div className="text-sm text-gray-500 dark:text-gray-400">{count} of {max} characters</div>
        <button
          onClick={onLearn}
          disabled={!value.trim()}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors ${
            !value.trim() ? 'bg-blue-300 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'
          }`}
        >
          Learn with Video
        </button>
      </div>
    </div>
  );
}
