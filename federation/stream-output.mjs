/** Large checkpoints must drain before stderr/errors can interleave with stdout. */
export function writeCheckpoint(value,stream=process.stdout) {
 return new Promise((resolve,reject)=>stream.write('OPENWIKI_CHECKPOINT '+JSON.stringify(value)+'\n',error=>error?reject(error):resolve()));
}
