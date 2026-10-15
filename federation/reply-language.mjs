/** One language policy for every user-facing model reply. */
import {readFileSync} from 'node:fs';
const policy=JSON.parse(readFileSync(new URL('./reply-language.json',import.meta.url),'utf8'));
export const replyLanguagePolicy=policy.reply;
export const repairLanguagePolicy=policy.repair;
export function isEnglishReply(answer='') {
  const prose=answer.replace(/```[\s\S]*?(?:```|$)|`[^`]*`|https?:\/\/\S+|^>.*$/gm,'');
  const words=(prose.match(/[a-z]+(?:'[a-z]+)?/gi) || []).length;
  return words>=3 && words>(prose.match(/[\u3400-\u9fff]/g) || []).length;
}
export function withReplyLanguage(system) {
  return system.includes(replyLanguagePolicy)?system:system+'\n'+replyLanguagePolicy;
}
