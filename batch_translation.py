"""Sequential translation of the selected Excel queue using the existing pipeline."""
import hashlib,json
from pathlib import Path
from batch_core import digest
from ocr_cache import POLICY

def translate_queue(queue,values,control,process,update=lambda _:None,log=lambda _:None,started=lambda _:None):
    queue.run(control,update=update,log=log)
    outputs=[];errors=[]
    def publish(job):
        queue.persist();warning=queue.save_excel();update(job.copy())
        if warning:log(warning)
    settings={k:v for k,v in values.items() if k not in {'api_key','controller','source_value','output'}}
    for index,job in enumerate(queue.jobs,1):
        control.check()
        if job['status']!='completed':errors.append(job.get('error') or 'Chưa nhập được video');continue
        source=queue.root/job['video'];output=source.parent/'translated_vi.mp4'
        signature=hashlib.sha256(json.dumps([job['sha256'],settings,POLICY],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if not values.get('force_ocr') and job.get('translation_status')=='completed' and job.get('translation_signature')==signature and output.is_file() and digest(output)==job.get('translation_sha256'):
            outputs.append(str(output));log(f'Bỏ qua video đã dịch: {job["name"]}');publish(job);continue
        try:
            job.update(translation_status='translating',translation_error='');publish(job);started({'source':str(source),'name':job['name'],'index':index,'total':len(queue.jobs)});log(f'Dịch video {index}/{len(queue.jobs)}: {job["name"]}')
            params=dict(values,source_value=str(source),output=output,controller=control)
            result=Path(process(**params,log=log)).resolve()
            if not result.is_file() or result!=output.resolve():raise RuntimeError('Không tìm thấy video đã xuất đúng vị trí dự án.')
            job.update(translation_status='completed',translation_output=str(result.relative_to(queue.root)),translation_signature=signature,translation_sha256=digest(result),translation_error='');outputs.append(str(result))
        except Exception as exc:
            job.update(translation_status='failed',translation_error=str(exc));errors.append(str(exc));log(f'Lỗi dịch {job["name"]}: {exc}')
        publish(job)
    return {'success':len(outputs),'failed':len(errors),'total':len(queue.jobs),'last_output':outputs[-1] if outputs else '', 'root':str(queue.root)}
