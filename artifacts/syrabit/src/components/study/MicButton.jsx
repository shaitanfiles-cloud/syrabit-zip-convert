/**
 * MicButton — speech-to-text trigger for the unified input bar.
 * Uses the browser SpeechRecognition API where available; otherwise
 * records a short clip and posts to the Sarvam Saaras backend.
 */
import { Mic, MicOff, Loader2 } from 'lucide-react';
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition';

export function MicButton({ onTranscript, language = 'en-IN', className = '', disabled = false }) {
  const { listening, error, start } = useSpeechRecognition({
    language,
    onResult: (text) => { if (onTranscript) onTranscript(text); },
  });

  return (
    <button
      type="button"
      onClick={start}
      disabled={disabled}
      className={[
        'inline-flex items-center justify-center w-9 h-9 rounded-full transition-colors',
        listening ? 'bg-red-500 text-white animate-pulse' : 'bg-muted hover:bg-muted/80 text-muted-foreground',
        disabled ? 'opacity-50 cursor-not-allowed' : '',
        className,
      ].join(' ')}
      aria-label={listening ? 'Stop recording' : 'Speak'}
      title={error ? `Mic error: ${error}` : (listening ? 'Listening… tap to stop' : 'Voice input')}
    >
      {listening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
    </button>
  );
}
