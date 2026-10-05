"""Decodificador mínimo do BU v2 (ASN.1 BER / IMPLICIT TAGS), 2024+."""
from dataclasses import dataclass
from typing import Optional

class BUDecodeError(ValueError): pass

@dataclass
class Tlv:
    tag:int; ini:int; fim:int; prox:int; construido:bool

SEQ=0x30; INTEGER=0x02; OCTET=0x04; ENUM=0x0A; GENSTR=0x1B
ctx=lambda n: 0x80|n
ctxc=lambda n: 0xA0|n

def _len(b,p):
    x=b[p]
    if x<0x80:return x,p+1
    if x==0x80:return -1,p+1
    n=x&0x7f
    if n>4: raise BUDecodeError('length too large')
    return int.from_bytes(b[p+1:p+1+n],'big'),p+1+n

def tlv(b,p=0,limit=None):
    limit=len(b) if limit is None else limit
    if p>=limit: raise BUDecodeError('TLV outside buffer')
    tag=b[p]
    if tag&0x1f==0x1f: raise BUDecodeError('high-tag-number unsupported')
    comp,ini=_len(b,p+1); constructed=bool(tag&0x20)
    if comp<0:
        if not constructed: raise BUDecodeError('indefinite primitive')
        q=ini
        while q<limit:
            if q+1<limit and b[q]==0 and b[q+1]==0:
                return Tlv(tag,ini,q,q+2,constructed)
            q=tlv(b,q,limit).prox
        raise BUDecodeError('missing EOC')
    fim=ini+comp
    if fim>limit: raise BUDecodeError('TLV exceeds buffer')
    return Tlv(tag,ini,fim,fim,constructed)

def children(b,t):
    if not t.construido: raise BUDecodeError('not constructed')
    out=[]; p=t.ini
    while p<t.fim:
        x=tlv(b,p,t.fim); out.append(x); p=x.prox
    return out

def integer(b,t): return int.from_bytes(b[t.ini:t.fim],'big',signed=True)
def text(b,t): return b[t.ini:t.fim].decode('latin1')
def hexv(b,t): return b[t.ini:t.fim].hex()

class Cursor:
    def __init__(self,b,t,name): self.b=b; self.x=children(b,t); self.i=0; self.name=name
    def req(self,tag,name):
        if self.i>=len(self.x) or self.x[self.i].tag!=tag: raise BUDecodeError(f'{self.name}.{name}: expected {tag:#x}')
        t=self.x[self.i]; self.i+=1; return t
    def one(self,tags,name):
        if self.i>=len(self.x) or self.x[self.i].tag not in tags: raise BUDecodeError(f'{self.name}.{name}: unexpected tag')
        t=self.x[self.i]; self.i+=1; return t
    def opt(self,tag):
        if self.i<len(self.x) and self.x[self.i].tag==tag: t=self.x[self.i]; self.i+=1; return t
        return None
    def optone(self,tags):
        if self.i<len(self.x) and self.x[self.i].tag in tags: t=self.x[self.i]; self.i+=1; return t
        return None
    def end(self):
        if self.i!=len(self.x): raise BUDecodeError(f'{self.name}: unexpected trailing field')

def header(b,t):
    c=Cursor(b,t,'header'); data=text(b,c.req(GENSTR,'dataGeracao')); x=c.one([ctx(1),ctx(2),ctx(3)],'idEleitoral')
    c.end(); return {'dataGeracao':data,'idEleitoral':{'tipo':{ctx(1):'processo',ctx(2):'pleito',ctx(3):'eleicao'}[x.tag],'valor':integer(b,x)}}

def municipio_zona(b,t):
    c=Cursor(b,t,'municipioZona'); r={'municipio':integer(b,c.req(INTEGER,'municipio')),'zona':integer(b,c.req(INTEGER,'zona'))}; c.end(); return r

def identificacao_secao(b,t):
    c=Cursor(b,t,'identificacaoSecao'); r={'municipioZona':municipio_zona(b,c.req(SEQ,'municipioZona')),'local':integer(b,c.req(INTEGER,'local')),'secao':integer(b,c.req(INTEGER,'secao'))}; c.end(); return r

def identificacao_urna(b,t):
    if t.tag==ctxc(0): return {'tipo':'secao','secao':identificacao_secao(b,t)}
    if t.tag==ctxc(1):
        c=Cursor(b,t,'identificacaoContingencia'); r={'tipo':'contingencia','municipioZona':municipio_zona(b,c.req(SEQ,'municipioZona'))}; c.end(); return r
    raise BUDecodeError('bad urna identification')

def carga(b,t):
    c=Cursor(b,t,'carga'); n=integer(b,c.req(INTEGER,'numeroInternoUrna')); fc=hexv(b,c.req(OCTET,'numeroSerieFC'))
    g=Cursor(b,c.req(SEQ,'identificadorGeradorMidia'),'gerador'); nome=text(b,g.req(GENSTR,'nome')); cert=text(b,g.req(GENSTR,'serialCertificadoTPM')); inst=text(b,g.req(GENSTR,'serialInstalacao')); g.end()
    data=text(b,c.req(GENSTR,'dataHoraCarga')); codigo=text(b,c.req(GENSTR,'codigoCarga')); c.end()
    return {'numeroInternoUrna':n,'numeroSerieFC':fc,'identificadorGeradorMidia':{'nome':nome,'serialCertificadoTPM':cert,'serialInstalacao':inst},'dataHoraCarga':data,'codigoCarga':codigo}

def urna(b,t):
    c=Cursor(b,t,'urna'); tipo=integer(b,c.req(ENUM,'tipoUrna')); versao=text(b,c.req(GENSTR,'versaoVotacao'))
    cr=Cursor(b,c.req(SEQ,'correspondenciaResultado'),'correspondenciaResultado'); ident=identificacao_urna(b,cr.one([ctxc(0),ctxc(1)],'identificacao')); cg=carga(b,cr.req(SEQ,'carga')); cr.end()
    arq=integer(b,c.req(ENUM,'tipoArquivo')); serie=hexv(b,c.req(OCTET,'numeroSerieFV')); c.end()
    return {'tipoUrna':tipo,'versaoVotacao':versao,'correspondenciaResultado':{'identificacao':ident,'carga':cg},'tipoArquivo':arq,'numeroSerieFV':serie}

def voto_votavel(b,t):
    c=Cursor(b,t,'voto'); tipo=integer(b,c.req(ctx(1),'tipoVoto')); qtd=integer(b,c.req(ctx(2),'quantidadeVotos')); ident=c.opt(ctxc(3)); partido=codigo=None
    if ident:
        iv=Cursor(b,ident,'identificacaoVotavel'); partido=integer(b,iv.req(INTEGER,'partido')); codigo=integer(b,iv.req(INTEGER,'codigo')); iv.end()
    ordem=integer(b,c.req(INTEGER,'ordemGeracaoHash')); h=hexv(b,c.req(OCTET,'hash')); c.end()
    return {'tipoVoto':tipo,'quantidadeVotos':qtd,'partido':partido,'codigo':codigo,'ordemGeracaoHash':ordem,'hash':h}

def total_cargo(b,t):
    c=Cursor(b,t,'totalVotosCargo'); cc=c.one([ctx(1),ctx(2)],'codigoCargo'); cargo={'tipo':'constitucional' if cc.tag==ctx(1) else 'livre','valor':integer(b,cc)}; ordem=integer(b,c.req(INTEGER,'ordemImpressao')); seq=c.req(SEQ,'votosVotaveis')
    votos=[voto_votavel(b,x) for x in children(b,seq)]; c.end(); return {'codigoCargo':cargo,'ordemImpressao':ordem,'votosVotaveis':votos}

def resultado_votacao(b,t):
    c=Cursor(b,t,'resultadoVotacao'); tipo=integer(b,c.req(ENUM,'tipoCargo')); comp=integer(b,c.req(INTEGER,'qtdComparecimento')); seq=c.req(SEQ,'totaisVotosCargo'); cargos=[total_cargo(b,x) for x in children(b,seq)]; c.end(); return {'tipoCargo':tipo,'qtdComparecimento':comp,'totaisVotosCargo':cargos}

def resultado_eleicao(b,t):
    c=Cursor(b,t,'resultadoEleicao'); eid=integer(b,c.req(INTEGER,'idEleicao')); apt=integer(b,c.req(INTEGER,'qtdEleitoresAptos')); aps=integer(b,c.req(INTEGER,'qtdEleitoresAptosSecao')); atte=integer(b,c.req(INTEGER,'qtdEleitoresAptosTTE')); seq=c.req(SEQ,'resultadosVotacao'); rv=[resultado_votacao(b,x) for x in children(b,seq)]; uh=hexv(b,c.req(OCTET,'ultimoHashVotosVotavel')); sig=hexv(b,c.req(OCTET,'assinaturaUltimoHashVotosVotavel')); c.end(); return {'idEleicao':eid,'qtdEleitoresAptos':apt,'qtdEleitoresAptosSecao':aps,'qtdEleitoresAptosTTE':atte,'resultadosVotacao':rv,'ultimoHashVotosVotavel':uh,'assinaturaUltimoHashVotosVotavel':sig}

def decode_envelope(b):
    root=tlv(b)
    if root.tag!=SEQ: raise BUDecodeError('envelope root is not SEQUENCE')
    c=Cursor(b,root,'envelope'); cab=header(b,c.req(SEQ,'cabecalho')); fase=integer(b,c.req(ENUM,'fase')); tem=c.opt(SEQ) is not None
    ident=identificacao_urna(b,c.one([ctxc(0),ctxc(1)],'identificacao')); tipo=integer(b,c.req(ENUM,'tipoEnvelope')); cif=c.opt(SEQ) is not None; cont=c.req(OCTET,'conteudo'); c.end()
    if root.prox!=len(b): raise BUDecodeError('trailing envelope bytes')
    return {'cabecalho':cab,'fase':fase,'temUrna':tem,'identificacao':ident,'tipoEnvelope':tipo,'cifrado':cif,'conteudo':b[cont.ini:cont.fim]}

def decode_bu_content(b):
    root=tlv(b)
    if root.tag!=SEQ or root.prox!=len(b): raise BUDecodeError('invalid BU root')
    c=Cursor(b,root,'bu'); cab=header(b,c.req(SEQ,'cabecalho')); fase=integer(b,c.req(ENUM,'fase')); u=urna(b,c.req(SEQ,'urna')); sec=identificacao_secao(b,c.req(SEQ,'identificacaoSecao')); emissao=text(b,c.req(GENSTR,'dataHoraEmissao'))
    dsa=c.one([ctxc(0),ctxc(1)],'dadosSecaoSA'); dados_secao=dados_sa=None
    if dsa.tag==ctxc(0):
        d=Cursor(b,dsa,'dadosSecao'); dados_secao={'dataHoraAbertura':text(b,d.req(GENSTR,'abertura')),'dataHoraEncerramento':text(b,d.req(GENSTR,'encerramento'))}; opt=d.opt(GENSTR); dados_secao['dataHoraDesligamentoVotoImpresso']=text(b,opt) if opt else None; d.end()
    else:
        d=Cursor(b,dsa,'dadosSA'); junta=integer(b,d.req(INTEGER,'junta')); turma=integer(b,d.req(INTEGER,'turma')); orig=d.opt(INTEGER); d.end(); dados_sa={'juntaApuradora':junta,'turmaApuradora':turma,'numeroInternoUrnaOrigem':integer(b,orig) if orig else None}
    compare=integer(b,c.req(INTEGER,'qtdEleitoresCompareceram')); det=c.opt(ctxc(1)); detal=None
    if det:
        d=Cursor(b,det,'det'); detal={'semBiometria':integer(b,d.req(INTEGER,'semBiometria')),'biometria':integer(b,d.req(INTEGER,'biometria')),'biografia':integer(b,d.req(INTEGER,'biografia'))}; d.end()
    seq=c.req(SEQ,'resultadosVotacaoPorEleicao'); resultados=[resultado_eleicao(b,x) for x in children(b,seq)]
    hist=c.req(SEQ,'historicoCodigosCarga'); historico=[text(b,x) for x in children(b,hist)]
    hvi=c.opt(SEQ); historico_impresso=None
    if hvi:
        historico_impresso=[]
        for x in children(b,hvi):
            d=Cursor(b,x,'historico'); historico_impresso.append({'idImpressoraVotos':integer(b,d.req(INTEGER,'idImpressora')),'idRepositorioVotos':integer(b,d.req(INTEGER,'idRepositorio')),'dataHoraLigamento':text(b,d.req(GENSTR,'ligamento'))}); d.end()
    c.end()
    return {'cabecalho':cab,'fase':fase,'urna':u,'identificacaoSecao':sec,'dataHoraEmissao':emissao,'dadosSecao':dados_secao,'dadosSA':dados_sa,'qtdEleitoresCompareceram':compare,'detalhamentoComparecimento':detal,'resultadosVotacaoPorEleicao':resultados,'historicoCodigosCarga':historico,'historicoVotoImpresso':historico_impresso}

def decode_bu_file(path):
    with open(path,'rb') as f: raw=f.read()
    env=decode_envelope(raw)
    if env['tipoEnvelope']!=1: raise BUDecodeError(f"tipoEnvelope={env['tipoEnvelope']}, esperado 1")
    if env['cifrado']: raise BUDecodeError('BU cifrado')
    bu=decode_bu_content(env['conteudo'])
    return env,bu

def extract_candidate_votes(bu, election_id=None, cargo_code=6):
    out=[]
    for e in bu['resultadosVotacaoPorEleicao']:
        if election_id is not None and e['idEleicao']!=election_id: continue
        for rv in e['resultadosVotacao']:
            for cargo in rv['totaisVotosCargo']:
                if cargo['codigoCargo']['valor']!=cargo_code: continue
                for v in cargo['votosVotaveis']:
                    if v['tipoVoto']==1 and v['codigo'] is not None:
                        out.append({'numero':str(v['codigo']).zfill(2),'partido':v['partido'],'votos':v['quantidadeVotos'],'tipoVoto':v['tipoVoto']})
    return out
