"use client"

import {cn} from '@/shared/lib/css'
import {Button} from '@/shared/ui/button'
import {Modal} from '@/shared/ui/modal'
import {Upload} from 'lucide-react'
import * as React from 'react'
import {SummaryModal} from '@/features/summary/ui/summary-modal'
import {toast} from 'sonner'
import {runInstant, startRealtime} from "@/features/ctg/lib/streaming"
import {useRouter} from "next/navigation"
import {nanoid} from "nanoid";

type Props = {
    open: boolean
    onOpenChange: (open: boolean) => void
}

export function UploadModal({open, onOpenChange}: Props) {
    const [dragOverFhr, setDragOverFhr] = React.useState(false)
    const [dragOverUterus, setDragOverUterus] = React.useState(false)
    const [fhrFile, setFhrFile] = React.useState<File | null>(null)
    const [uterusFile, setUterusFile] = React.useState<File | null>(null)
    const [loading, setLoading] = React.useState(false)
    const [showSummary, setShowSummary] = React.useState(false)
    const [instantResult, setInstantResult] = React.useState<any>(null)
    const fhrRef = React.useRef<HTMLInputElement>(null)
    const uterusRef = React.useRef<HTMLInputElement>(null)
    const router = useRouter()
    const [mode, setMode] = React.useState<'instant' | 'realtime'>('realtime')
    const [speed, setSpeed] = React.useState<number>(4)

    const MAX_SIZE_BYTES = 30 * 1024 * 1024 // 30 MB

    const pickFile = (file: File, kind: 'fhr' | 'uterus') => {
        if (file.size > MAX_SIZE_BYTES) {
            toast.error('Файл превышает 30 МБ')
            return false
        }
        if (kind === 'fhr') setFhrFile(file)
        else setUterusFile(file)
        return true
    }

    const handleStart = async () => {
        if (!fhrFile || !uterusFile) {
            toast.error('Загрузите оба файла: ЧСС и матка')
            return
        }
        setLoading(true)
        try {
            const monitor_id = nanoid()
            if (mode === 'instant') {
                const res = await runInstant(fhrFile, uterusFile, {monitor_id})
                try {
                    sessionStorage.setItem('instant_result', JSON.stringify(res))
                } catch {
                }
                setInstantResult(res)
                toast.success('Мгновенная обработка выполнена')
                onOpenChange(false)
                setShowSummary(true)
            } else {
                const resp = await startRealtime(fhrFile, uterusFile, {monitor_id, interval_sec: 1, speed})
                const id = resp.monitor_id || monitor_id
                if (typeof window !== 'undefined') {
                    sessionStorage.setItem('ktg_monitor_id', id)
                }
                onOpenChange(false)
                router.push('/start-process')
            }
        } catch (e) {
            console.error(e)
            toast.error('Ошибка при запуске обработки')
        } finally {
            setLoading(false)
        }
    }

    return (
        <>
            <Modal open={open} onOpenChange={onOpenChange}>
                <div onClick={(e) => {
                    if (e.currentTarget === e.target) {
                        onOpenChange(false)
                    }

                }}
                    className="h-full w-full flex flex-col"
                >
                    <div className="flex-1"/>
                    <div className="px-4 md:px-8">
                        <div className="text-center text-2xl md:text-4xl font-semibold mb-6">Загрузите eXel файлы</div>

                        <div className="grid gap-4">
                            <div
                                className={cn('relative rounded-2xl border-2 border-dashed border-input bg-input/10 px-6 py-12',
                                    dragOverFhr && 'bg-input/20')}
                                onDragOver={e => {
                                    e.preventDefault();
                                    setDragOverFhr(true)
                                }}
                                onDragLeave={() => setDragOverFhr(false)}
                                onDrop={e => {
                                    e.preventDefault();
                                    setDragOverFhr(false);
                                    const f = e.dataTransfer.files?.[0];
                                    if (f) pickFile(f, 'fhr')
                                }}
                                onClick={() => fhrRef.current?.click()}
                            >
                                <input ref={fhrRef} type="file" className="hidden" accept=".csv,.xls,.xlsx"
                                       onChange={e => {
                                           const f = e.target.files?.[0];
                                           if (f) pickFile(f, 'fhr')
                                       }}/>
                                <div className="flex flex-col items-center justify-center gap-3 text-center">
                                    <Upload className="size-6 text-muted-foreground"/>
                                    <div className="text-muted-foreground"><span className="underline">Загрузите данные ЧСС ребёнка</span>
                                    </div>
                                    <div
                                        className="text-xs text-muted-foreground">{fhrFile ? fhrFile.name : 'Файл не выбран'}</div>
                                </div>
                            </div>

                            <div
                                className={cn('relative rounded-2xl border-2 border-dashed border-input bg-input/10 px-6 py-12',
                                    dragOverUterus && 'bg-input/20')}
                                onDragOver={e => {
                                    e.preventDefault();
                                    setDragOverUterus(true)
                                }}
                                onDragLeave={() => setDragOverUterus(false)}
                                onDrop={e => {
                                    e.preventDefault();
                                    setDragOverUterus(false);
                                    const f = e.dataTransfer.files?.[0];
                                    if (f) pickFile(f, 'uterus')
                                }}
                                onClick={() => uterusRef.current?.click()}
                            >
                                <input ref={uterusRef} type="file" className="hidden" accept=".csv,.xls,.xlsx"
                                       onChange={e => {
                                           const f = e.target.files?.[0];
                                           if (f) pickFile(f, 'uterus')
                                       }}/>
                                <div className="flex flex-col items-center justify-center gap-3 text-center">
                                    <Upload className="size-6 text-muted-foreground"/>
                                    <div className="text-muted-foreground"><span className="underline">Загрузите данные сократительной активности матки</span>
                                    </div>
                                    <div
                                        className="text-xs text-muted-foreground">{uterusFile ? uterusFile.name : 'Файл не выбран'}</div>
                                </div>
                            </div>
                        </div>

                        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
                            <button type="button" onClick={() => setMode('instant')}
                                    className={cn('rounded-2xl border px-4 py-6 text-left', mode === 'instant' ? 'border-primary/60 bg-primary/5' : 'border-input bg-input/10')}>
                                <div className="flex items-start gap-3">
                                    <div
                                        className={cn('mt-1 size-4 rounded-full border', mode === 'instant' ? 'bg-primary border-primary' : 'border-muted-foreground/40')}/>
                                    <div>
                                        <div className="text-xl">Мгновенная обработка</div>
                                    </div>
                                </div>
                            </button>
                            <button type="button" onClick={() => setMode('realtime')}
                                    className={cn('rounded-2xl border px-4 py-6 text-left', mode === 'realtime' ? 'border-primary/60 bg-primary/5' : 'border-input bg-input/10')}>
                                <div className="flex items-start gap-3">
                                    <div
                                        className={cn('mt-1 size-4 rounded-full border', mode === 'realtime' ? 'bg-primary border-primary' : 'border-muted-foreground/40')}/>
                                    <div className="flex-1">
                                        <div className="text-xl">В реальном времени (x{speed})</div>
                                        <div className="mt-4 flex items-center gap-3"
                                             onClick={e => e.stopPropagation()}>
                                            <div className="text-xs opacity-60">x1</div>
                                            <input type="range" min={1} max={50} step={1} value={speed}
                                                   onChange={e => setSpeed(Number(e.target.value))} className="w-full"/>
                                            <div className="text-xs opacity-60">x50</div>
                                        </div>
                                    </div>
                                </div>
                            </button>
                        </div>
                    </div>

                    <div className="py-8 flex justify-center">
                        <Button size="lg" className="rounded-xl px-8" onClick={handleStart} disabled={loading}>К
                            демонстрации</Button>
                    </div>

                    {loading && (
                        <div
                            className="absolute inset-0 flex items-center justify-center bg-background/60 backdrop-blur-sm">
                            <div
                                className="size-10 rounded-full border-2 border-muted-foreground/20 border-t-foreground animate-spin"/>
                        </div>
                    )}
                </div>
            </Modal>
            {showSummary && (
                <SummaryModal onClose={() => setShowSummary(false)} result={instantResult}/>
            )}
        </>
    )
}
