/** Personal recall/rewriting uses saved user records, not public search. */
import {readFileSync} from 'node:fs';
const identityPattern=new RegExp(JSON.parse(readFileSync(new URL('./personal-query-patterns.json',import.meta.url),'utf8')).identity,'iu');
export function personalIdentityQuestion(question='') {
 return typeof question==='string' && identityPattern.test(question.trim());
}
export function profileOnlyQuestion(question='') {
 if(personalIdentityQuestion(question))return true;
 const text=question.replace(/[\s，。！？!?,.]/gu,'');
 if(/市场|行情|最新|招聘|推荐|查找|搜索|联网|适合.*岗位/u.test(text))return false;
 return /(?:帮我|给我)(?:修改|改|润色|重写)简历|(?:帮我|给我|我的背景|我的经历).*(?:自我介绍|个人简介)|^(?:你)?(?:了解|知道|记得|记住).*(?:我|个人资料)|^我是(?:谁|做什么的)|^我(?:会|有)(?:哪些|什么)(?:技能|经验|经历)|(?:我的|这份)(?:简历|个人资料|背景|工作经历|项目经历).*(?:写了什么|有什么|有哪些|是什么)|(?:复述|回顾|总结|介绍|说说|修改|改|润色|重写).*(?:我的简历|我的资料|我的背景|我的经历|我的目标|我的偏好)|^(?:我的目标|我的偏好)(?:是什么|有哪些)?$/u.test(text);
}
