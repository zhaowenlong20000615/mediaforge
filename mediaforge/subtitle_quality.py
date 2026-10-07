"""Readable cue grouping around Whisper's own word timestamps."""
import re
import unicodedata


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {'W','F'} else 1 for c in text)


def cues_from_words(words,line_width=28,max_seconds=6):
    cues=[];chunk=[]
    def lines(items):
        result=[];line=''
        for item in items:
            value=item['text']
            if line and display_width(line+value)>line_width:
                result.append(line.strip());line=value.lstrip()
            else:line+=value.lstrip() if not line else value
        if line:result.append(line.strip())
        return result
    def flush():
        if not chunk:return
        start=max(0,float(chunk[0]['start']),cues[-1]['end'] if cues else 0)
        end=max(start+.1,min(start+max_seconds,float(chunk[-1]['end'])))
        cues.append({'start':start,'end':end,'text':'\n'.join(lines(chunk))})
        chunk.clear()
    for word in words:
        if not word['text'].strip():continue
        # One ASR word can itself be an entire sentence or a long identifier.
        parts=[];piece=''
        for char in word['text']:
            if piece and display_width(piece+char)>line_width:parts.append(piece);piece=''
            piece+=char
        if piece:parts.append(piece)
        span=max(.1,float(word['end'])-float(word['start']))
        for i,part in enumerate(parts):
            unit={'text':part,'start':float(word['start'])+span*i/len(parts),'end':float(word['start'])+span*(i+1)/len(parts)}
            if chunk and (len(lines([*chunk,unit]))>2 or unit['end']-float(chunk[0]['start'])>max_seconds):flush()
            chunk.append(unit)
            if re.search(r'[。！？.!?]$',part.strip()) and unit['end']-float(chunk[0]['start'])>=.8:flush()
    flush()
    return cues
