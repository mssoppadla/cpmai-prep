# Integrated Solution: Fix Network Errors + Prevent Data Loss

## Problem Statement

Users taking exams experience:
1. **Network failures** - QUIC errors, 401 timeouts, connection drops
2. **Data loss** - exam answers disappear when errors occur
3. **No recovery** - can't resume from where they left off

**Impact:** Users lose progress, get frustrated, abandon exams

---

## Root Causes (Confirmed)

### Network Issues
1. **QUIC Protocol Errors** (ERR_QUIC_PROTOCOL_ERROR)
   - HTTP/3 QUIC on UDP/443 may not be properly enabled on production VPS
   - Browser falls back to HTTP/2, but takes 30+ seconds
   - Causes timeout errors

2. **401 Auth Errors**
   - Access token expires during exam (4 hour TTL)
   - Silent refresh fails or takes too long
   - User gets logged out mid-exam

3. **Connection Timeouts**
   - `PATCH /exams/attempts/{id}/answer` requests take > 30 seconds
   - Frontend times out, considers it failed
   - User has no idea if answer was saved

4. **DNS/Network Issues**
   - `ERR_NAME_NOT_RESOLVED` suggests DNS resolution failing
   - Network instability causing connection drops

### Data Loss
1. **No auto-save**
   - Answers only saved when user explicitly selects them
   - If network fails during that save, answer is lost

2. **No local backup**
   - Browser doesn't cache answers locally
   - Complete reliance on server-side save

3. **No recovery workflow**
   - If user loses connection, no way to resume
   - Must start exam over from Q1

---

## Integrated Solution (2 Parts)

### PART 1: Fix Network Issues

**Goal:** Ensure requests don't timeout or fail

#### 1.1 Increase Request Timeout
- Currently: 30 seconds
- Change to: 60 seconds (allow for slow networks)
- Reason: Some answers take 30-45 seconds to save on slow backends

#### 1.2 Add Retry Logic
- Retry on QUIC errors (up to 2 times)
- Retry on connection timeouts (up to 2 times)
- Use exponential backoff (100ms, 200ms)

#### 1.3 Fix 401 Auth Issues
- Improve silent refresh: refresh BEFORE timeout, not after
- If request would take > 60s and auth is expiring soon, refresh preemptively
- Prevent auth expiry during exam

#### 1.4 Optimize Backend Performance
- Check `/exams/attempts/{id}/answer` endpoint performance
- May need database indexes or query optimization
- If consistently slow, that's the real issue

#### 1.5 Verify QUIC Firewall Rule
- Confirm UDP/443 is open on production VPS
- If not, disable HTTP/3 at Caddy level
- Document the choice

---

### PART 2: Prevent Data Loss

**Goal:** Even if network fails, user doesn't lose answers

#### 2.1 Auto-Save Mechanism
```
User selects answer → Immediately show as selected (optimistic)
                   → Send PATCH request to server
                   → Cache locally in indexedDB
                   → Show "Saving..." indicator
                   → On success: show "✓ Saved"
                   → On failure: show "Retrying..." + retry auto
```

#### 2.2 Local IndexedDB Backup
```
Browser IndexedDB (backup):
  - exam_id: 123
  - question_id: 5
  - selected_letter: "B"
  - saved_at: 2026-08-07T10:23:45Z
  - synced_to_server: false

On page load:
  1. Check server for latest attempt state
  2. Check indexedDB for locally cached answers
  3. Merge: prefer server (source of truth), fill gaps from local cache
  4. Sync any unsaved local answers to server
```

#### 2.3 Resume Workflow
```
Scenario: User's connection drops at Q35

On next page load:
  1. Detect: attempt exists but not submitted
  2. Show: "Resume Exam: You were on Q35. Resume or start over?"
  3. On resume:
     - Fetch latest attempt state from server
     - Load from local cache if server data missing
     - Show Q35 with user's previous answer selected
     - User can continue from Q36

Data sources (in priority order):
  1. Server (authoritative)
  2. Local indexedDB (backup)
  3. Worst case: start over
```

#### 2.4 Browser Unload Protection
```
User tries to close tab/refresh while in exam:
  1. beforeunload event fires
  2. Save all pending answers to indexedDB first
  3. Quick PATCH request to server (fire-and-forget)
  4. Show: "You have unsaved answers. Are you sure you want to leave?"
```

---

## Implementation Checklist

### Backend (Python/FastAPI)

- [ ] **Verify QUIC firewall rule**
  ```bash
  sudo ufw status | grep 443
  # Should show: 443/tcp ALLOW and 443/udp ALLOW
  ```

- [ ] **Optimize saveAnswer endpoint**
  ```python
  # Measure query time
  @app.patch("/exams/attempts/{id}/answer")
  async def save_answer(id: int, payload: AnswerIn, db: Session):
      import time
      t0 = time.time()
      # ... save logic ...
      duration = time.time() - t0
      log(f"saveAnswer took {duration}s for Q{payload.question_id}")
  ```

- [ ] **Add idempotent save** (handle retries gracefully)
  ```python
  # If same answer submitted twice, just return 200 (not error)
  existing = db.query(ExamAttemptAnswer).filter(
      ExamAttemptAnswer.exam_session_id == id,
      ExamAttemptAnswer.question_id == payload.question_id
  ).first()
  
  if existing and existing.selected_letter == payload.selected_letter:
      return {"status": "already_saved"}  # idempotent
  ```

- [ ] **Add resume endpoint**
  ```python
  @app.get("/exams/attempts/{id}/resume")
  async def resume_attempt(id: int, db: Session):
      attempt = db.query(ExamSession).get(id)
      return {
          "attempt": attempt,
          "answers": [ans.to_dict() for ans in attempt.answers],
          "last_saved_at": max(ans.answered_at for ans in attempt.answers)
      }
  ```

- [ ] **Add bulk sync endpoint**
  ```python
  @app.post("/exams/attempts/{id}/answers/sync")
  async def sync_answers(id: int, answers: List[AnswerIn], db: Session):
      # Save multiple answers at once
      # Used when resuming after timeout
      results = []
      for ans in answers:
          # save logic...
          results.append({"question_id": ans.question_id, "status": "saved"})
      return results
  ```

### Frontend (TypeScript/React)

- [ ] **Increase timeout**
  ```typescript
  // In api.ts, change from 30s to 60s
  signal: AbortSignal.timeout?.(60000)
  ```

- [ ] **Add retry logic**
  ```typescript
  // fetchWithRetry() - retry on QUIC/timeout errors
  async function fetchWithRetry(url, opts, maxRetries = 2) {
      for (let attempt = 0; attempt <= maxRetries; attempt++) {
          try {
              return await fetch(url, opts)
          } catch (err) {
              if (isRetryable(err) && attempt < maxRetries) {
                  const delay = 100 * Math.pow(2, attempt)
                  await new Promise(r => setTimeout(r, delay))
              } else {
                  throw err
              }
          }
      }
  }
  ```

- [ ] **Set up IndexedDB**
  ```typescript
  // lib/exam-cache.ts
  class ExamCache {
      async saveAnswer(attemptId, answer) {
          const db = await openDB('cpmai-exams')
          await db.put('answers', {
              attempt_id: attemptId,
              question_id: answer.question_id,
              selected_letter: answer.selected_letter,
              saved_at: new Date(),
              synced_to_server: false
          })
      }
      
      async getSavedAnswers(attemptId) {
          const db = await openDB('cpmai-exams')
          return await db.getAll('answers', 
              IDBKeyRange.bound([attemptId, 0], [attemptId, Infinity]))
      }
  }
  ```

- [ ] **Auto-save answers**
  ```typescript
  // In exam page component
  const handleAnswerChange = async (questionId, answer) => {
      // 1. Show as selected immediately (optimistic)
      setAnswers(prev => ({ ...prev, [questionId]: answer }))
      setStatus(prev => ({ ...prev, [questionId]: 'saving' }))
      
      // 2. Save to local cache first
      await examCache.saveAnswer(attemptId, { question_id: questionId, ...answer })
      
      // 3. Send to server (with auto-retry)
      try {
          await api.exams.saveAnswer(attemptId, { question_id: questionId, ...answer })
          setStatus(prev => ({ ...prev, [questionId]: 'saved' }))
      } catch (err) {
          setStatus(prev => ({ ...prev, [questionId]: 'failed_retrying' }))
          // Retry automatically in background
          retryQueue.add(attemptId, { question_id: questionId, ...answer })
      }
  }
  ```

- [ ] **Resume workflow**
  ```typescript
  // On page load
  useEffect(() => {
      const checkResume = async () => {
          const cached = await examCache.getAttempt(attemptId)
          const server = await api.exams.getAttempt(attemptId)
          
          if (!server.submitted_at && cached?.last_saved_at) {
              // In-progress attempt with cached state
              showResumeDialog()
          }
      }
      checkResume()
  }, [])
  ```

- [ ] **Browser unload protection**
  ```typescript
  useEffect(() => {
      const handleUnload = async (e) => {
          // Try to save any pending answers
          const pending = Object.entries(dirtyAnswers)
          if (pending.length > 0) {
              await examCache.saveBulk(attemptId, pending)
              e.preventDefault()
              e.returnValue = "You have unsaved answers"
          }
      }
      
      window.addEventListener('beforeunload', handleUnload)
      return () => window.removeEventListener('beforeunload', handleUnload)
  }, [dirtyAnswers])
  ```

- [ ] **Show save status**
  ```typescript
  // Visual feedback for each question
  const getSaveStatus = (questionId) => {
      const status = saveStatus[questionId]
      return {
          saving: <Spinner />,
          saved: <CheckIcon color="green" />,
          failed_retrying: <AlertIcon color="orange" title="Retrying..." />,
          error: <AlertIcon color="red" title="Failed to save" />
      }[status]
  }
  ```

---

## Deployment Plan

### Phase 1: Fix Network Issues (Day 1)
1. Check QUIC firewall rule on VPS (confirm UDP/443)
2. Optimize backend saveAnswer endpoint (profile queries)
3. Increase timeout from 30s → 60s
4. Add retry logic to fetchWithRetry()

### Phase 2: Prevent Data Loss (Day 2-3)
1. Implement IndexedDB cache
2. Add auto-save on every answer change
3. Add resume workflow
4. Add browser unload protection

### Phase 3: Test & Monitor (Day 4)
1. Test all error scenarios
2. Monitor error rates on production
3. Measure: saveAnswer response times
4. Verify: zero data loss on network failures

---

## Testing Scenarios

### Test 1: Slow Network (Timeout Risk)
```
1. Open exam
2. In Chrome DevTools: Network tab → Throttle to "Slow 3G"
3. Answer Q1-Q5
4. Verify: answers saved despite slow network
5. Verify: "Saving..." indicator shows
6. Verify: no data loss
```

### Test 2: QUIC Protocol Error
```
1. Open exam
2. In Chrome DevTools: Disable QUIC (Settings → Disable QUIC)
3. Answer questions
4. Should automatically retry and succeed
5. Verify: no error shown to user
```

### Test 3: Network Disconnection
```
1. Answer Q1-Q5
2. Disable WiFi
3. Try to answer Q6
4. Verify: "Retrying..." shown, not error
5. Re-enable WiFi
6. Verify: Q6 eventually saves
7. Refresh page
8. Verify: Q1-Q6 all there, can resume at Q7
```

### Test 4: Browser Crash
```
1. Answer Q1-Q10 (don't submit)
2. Kill browser process
3. Reopen browser
4. Go to exam page
5. Verify: "Resume" option shown
6. Click Resume
7. Verify: Q1-Q10 all restored, on Q11
```

### Test 5: Token Expiry
```
1. Clear refresh token from localStorage
2. Answer question
3. Verify: silent refresh triggers
4. Verify: if refresh fails, graceful error
5. Verify: answer still saved locally
```

---

## Success Criteria

✅ **Network issues fixed:**
- [ ] No ERR_QUIC_PROTOCOL_ERROR on exam page
- [ ] No timeouts on saveAnswer (< 60s)
- [ ] 401 errors don't interrupt exam
- [ ] Automatic retries work silently

✅ **Data loss prevented:**
- [ ] Zero exam answers lost on network failure
- [ ] Users can resume after timeout
- [ ] Local cache acts as backup
- [ ] Visual feedback for save status

✅ **User experience:**
- [ ] No error messages mid-exam (silent retries)
- [ ] Can continue answering while retrying
- [ ] Resume workflow works smoothly
- [ ] Unload warning if unsaved answers

---

## Rollback Plan

If issues arise:

1. **Revert code changes** (removes new features)
2. **Keep database tables** (error_logs, no changes to exam tables)
3. **No migration rollback needed** (only added, didn't change existing)
4. **Users' exam progress preserved** (no data deletion)

---

## Next Steps

1. **Confirm this is the right approach** ✓ (you've confirmed)
2. **Run server diagnostics** to understand timeout root cause
3. **Implement Phase 1** (network fixes) - ASAP
4. **Implement Phase 2** (data persistence) - following day
5. **Deploy to production** and monitor
