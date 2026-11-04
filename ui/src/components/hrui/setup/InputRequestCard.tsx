// The question a task ended on (Tasks 3.2), answered as an input_response. Above the composer, which
// stays: a message written there instead passes the question over. A `secret` is typed here because
// the composer's text enters the conversation, and this doesn't.
import { useState } from 'react';
import type { InputRequest } from '@/lib/conversation';
import './input-request.css';

function choicesOf(r: InputRequest): { id: string; label: string }[] {
  if (r.options?.length) return r.options;
  return r.kind === 'confirm' ? [{ id: 'yes', label: 'Yes' }, { id: 'no', label: 'No' }] : [];
}

/** Whether the question can no longer be answered. `now` is in seconds, as `expires_at` is. */
export function requestExpired(r: InputRequest, now: number = Date.now() / 1000): boolean {
  return typeof r.expires_at === 'number' && r.expires_at <= now;
}

export function InputRequestCard({ request, disabled, onAnswer }: {
  request: InputRequest;
  disabled?: boolean;
  /** `answer` goes to the server; `shown` is what the thread shows as the person's message. */
  onAnswer: (answer: string, shown: string) => void;
}) {
  const [value, setValue] = useState('');
  const secret = request.kind === 'secret';
  const choices = choicesOf(request);
  if (requestExpired(request)) {
    return <div className="input-request" role="status"><p className="input-request-note">This question has expired. Write a message to go on.</p></div>;
  }
  const submit = () => {
    const v = value.trim();
    if (!v || disabled) return;
    setValue('');
    onAnswer(v, secret ? 'Answer sent privately' : v);
  };
  return (
    <form className="input-request" aria-label="Answer the question" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <p className="input-request-lead">Waiting for your answer</p>
      {choices.length ? (
        <div className="input-request-choices">
          {choices.map((o) => (
            <button key={o.id} type="button" className="btn small" disabled={disabled} onClick={() => onAnswer(o.id, o.label)}>{o.label}</button>
          ))}
        </div>
      ) : (
        <div className="input-request-field">
          <input type={secret ? 'password' : 'text'} value={value} onChange={(e) => setValue(e.target.value)}
            aria-label={request.prompt} placeholder={secret ? 'Your answer stays private' : 'Your answer'}
            autoComplete="off" spellCheck={false} disabled={disabled} />
          <button type="submit" className="btn small primary" disabled={disabled || !value.trim()}>Send answer</button>
        </div>
      )}
      {secret ? <p className="input-request-note">Only this task can use it. It isn&apos;t saved or shown in the conversation, unless the agent repeats it.</p> : null}
    </form>
  );
}
