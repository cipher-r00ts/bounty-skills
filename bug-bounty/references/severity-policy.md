# Bug bounty severity and exploit-chain policy

Our standalone finding/report focus is demonstrated **Medium, High, or Critical**
impact. Do not pursue, package, or submit standalone Informational or Low issues,
even if a program accepts them. Program scope, conduct, and stricter submission
requirements still apply.

Low-severity behavior is worth retaining only as a gadget in a concrete plausible
exploit chain. Record it briefly in private investigation notes with:

- The evidenced capability it supplies, such as obtaining a required value or
  crossing one limited boundary.
- The specific linked hypothesis/chain it advances and the stronger outcome sought.
- Remaining prerequisites and the next bounded test that could establish the chain.

A vague claim that something might chain later is insufficient. If there is no
credible chain role or permitted next test, stop pursuing it. Do not spend time
on a standalone report, screenshot package, or independent review of a low gadget
solely to make it look reportable.

Assess the combined chain on end-to-end demonstrated impact. A useful gadget
remains Low in isolation; its presence does not establish that the whole chain
works or reaches Medium. Only promote the combined finding once acquisition,
delivery, relevant boundaries, and consequence are evidenced and reproduced.

Keep technical validity separate from researcher submission policy. An authentic
Low issue is below our focus, not technically disproven. Preserve a brief policy
disposition where needed; never inflate severity or fabricate a refutation to
clear a queue. Unknown impact is not automatically Low: allow a bounded impact
assessment when concrete evidence suggests a stronger outcome.

Routine informational facts may remain in the target map as context; they are
not vulnerability work items. The agent and triager apply this policy: the helper
checks evidence/review records but does not independently calculate severity.
