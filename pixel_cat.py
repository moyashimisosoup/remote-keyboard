"""Code-native pixel cat, shared between the phone, panel and tray."""
import struct
from pathlib import Path
COLORS={'#':(55,49,61,255),'w':(255,246,220,255),'o':(238,176,99,255),'p':(241,151,166,255),'.':(0,0,0,0)}
SIZE=20
_grid=[['.']*SIZE for _ in range(SIZE)]
def rect(x,y,w,h,c):
    for yy in range(y,y+h):
        for xx in range(x,x+w): _grid[yy][xx]=c
# Upright soft ears and a round, chubby face.
rect(3,1,2,2,'#'); rect(15,1,2,2,'#')
rect(2,3,5,5,'#'); rect(13,3,5,5,'#')
rect(3,3,2,3,'p'); rect(15,3,2,3,'p')
rect(5,4,10,2,'#'); rect(3,6,14,9,'#'); rect(2,8,16,5,'#')
rect(4,6,12,8,'w'); rect(3,8,14,5,'w')
rect(5,6,3,2,'o'); rect(12,6,3,1,'o')
rect(6,9,2,2,'#'); rect(12,9,2,2,'#')
rect(6,9,1,1,'w'); rect(12,9,1,1,'w')
rect(4,11,2,1,'p'); rect(14,11,2,1,'p')
rect(9,11,2,1,'p'); rect(9,12,1,1,'#'); rect(11,12,1,1,'#')
# Little paws and curled tail.
rect(6,14,8,4,'#'); rect(7,14,6,3,'w'); rect(5,17,4,2,'#'); rect(11,17,4,2,'#')
rect(6,17,2,1,'w'); rect(12,17,2,1,'w')
rect(14,15,4,2,'#'); rect(17,13,2,3,'#'); rect(15,15,2,1,'o'); rect(17,14,1,1,'o')
PIXELS=tuple(''.join(row) for row in _grid)
def write_assets(root):
    root=Path(root); rects=[]
    for y,row in enumerate(PIXELS):
        for x,c in enumerate(row):
            if c!='.':
                r,g,b,_=COLORS[c]
                rects.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#{r:02x}{g:02x}{b:02x}"/>')
    (root/'cat.svg').write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" shape-rendering="crispEdges">'+''.join(rects)+'</svg>',encoding='utf-8')
    rgba=b''.join(bytes((COLORS[c][2],COLORS[c][1],COLORS[c][0],COLORS[c][3])) for row in reversed(PIXELS) for c in row)
    mask=b''.join(struct.pack('>I',sum(1<<(31-x) for x,c in enumerate(row) if c=='.')) for row in reversed(PIXELS))
    bmp=struct.pack('<IiiHHIIiiII',40,SIZE,SIZE*2,1,32,0,len(rgba)+len(mask),0,0,0,0)+rgba+mask
    (root/'cat.ico').write_bytes(struct.pack('<HHH',0,1,1)+struct.pack('<BBBBHHII',SIZE,SIZE,0,0,1,32,len(bmp),22)+bmp)
if __name__=='__main__': write_assets(Path(__file__).resolve().parent)
