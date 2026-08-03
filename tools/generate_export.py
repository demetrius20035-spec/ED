# -*- coding: utf-8 -*-
"""
Генератор выгрузки ДХ по описанию метаданных.

Читает metadata_selected_cleaned.json (дамп описания метаданных из 1С) и генерирует:
  1. Секцию типов в EnterpriseData_1_6_23_Extended.xsd
     (между маркерами "НАЧАЛО/КОНЕЦ ГЕНЕРИРУЕМОЙ СЕКЦИИ");
  2. Область ГенерируемыйКодДХ в EnterpriseData.bsl
     (между маркерами "НАЧАЛО/КОНЕЦ ГЕНЕРИРУЕМОГО КОДА"):
     ОписаниеВыгрузки(), функции ПолучитьДанные_Ген_*, КлючевоеСвойствоГен_*,
     ВыгрузитьРегистр_Ген_*, диспетчеры.

Ручные обработчики (Проекты/Сети, СчетПокупателю, Номенклатура, Договоры,
Реализация, Поступление) НЕ трогаются: для них генерируются только строки
ОписаниеВыгрузки. Типы ручной зоны XSD не генерируются повторно.

Запуск:  python3 tools/generate_export.py
"""

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "metadata_selected_cleaned.json"
XSD_PATH = ROOT / "EnterpriseData_1_6_23_Extended.xsd"
BSL_PATH = ROOT / "EnterpriseData.bsl"

XSD_BEGIN = "НАЧАЛО ГЕНЕРИРУЕМОЙ СЕКЦИИ"
XSD_END = "КОНЕЦ ГЕНЕРИРУЕМОЙ СЕКЦИИ"
BSL_BEGIN = "НАЧАЛО ГЕНЕРИРУЕМОГО КОДА"
BSL_END = "КОНЕЦ ГЕНЕРИРУЕМОГО КОДА"

# ----------------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------------

# Объекты с полностью ручными обработчиками в ВыгрузитьДанные:
# генерируются только строки ОписаниеВыгрузки (имена файлов/сущностей закреплены,
# под них уже написаны парсеры на стороне приёмника)
MANUAL_ROWS = {
    "Справочник.Проекты": [
        {"entity": "Проект", "file": "proekt.xml", "selection": "Элементы", "posted": False},
        {"entity": "Сеть", "file": "set.xml", "selection": "Группы", "posted": False},
    ],
    "Документ.СчетНаОплатуПокупателю": [
        {"entity": "СчетПокупателю", "file": "schet.xml", "selection": "Все", "posted": True},
    ],
    "Справочник.Номенклатура": [
        {"entity": "Номенклатура", "file": "nomenklatura.xml", "selection": "Элементы", "posted": False},
    ],
    "Справочник.ДоговорыКонтрагентов": [
        {"entity": "Договор", "file": "dogovor.xml", "selection": "Все", "posted": False},
    ],
    "Документ.РеализацияТоваровУслуг": [
        {"entity": "РеализацияТоваровУслуг", "file": "realizaciya.xml", "selection": "Все", "posted": True},
    ],
    "Документ.ПоступлениеТоваровУслуг": [
        {"entity": "ПоступлениеТоваровУслуг", "file": "postuplenie.xml", "selection": "Все", "posted": True},
    ],
}

# Объекты, которые целиком формирует и пишет попутная выгрузка
# СоздатьКлючевоеСвойство_* (типы XSD - в типовом пакете или ручной зоне):
# в генерируемом диспетчере для них вызывается ПолучитьКлючевоеСвойство
SIDE_WRITTEN = {
    "Справочник.Валюты",
    "Справочник.Организации",
    "Справочник.Контрагенты",
    "Справочник.Склады",
    "Справочник.Кассы",
    "Справочник.Подразделения",
    "Справочник.Единицы",
    "Справочник.БанковскиеСчета",
    "Справочник.Банки",
    "Справочник.СтатьиЗатрат",
}

# Ссылки на объекты с ручными обёртками ключевых свойств:
# ОбъектМетаданных -> квалифицированное имя типа XDTO для элемента
REF_MANUAL = {
    "Справочник.Валюты": "ns1:КлючевыеСвойстваВалюта",
    "Справочник.Организации": "ns1:КлючевыеСвойстваОрганизация",
    "Справочник.Контрагенты": "ns1:КлючевыеСвойстваКонтрагент",
    "Справочник.ДоговорыКонтрагентов": "ns1:КлючевыеСвойстваДоговор",
    "Справочник.Номенклатура": "ns1:КлючевыеСвойстваНоменклатура",
    "Справочник.КлассификаторЕдиниц": "ns1:КлючевыеСвойстваЕдиницаИзмерения",
    "Справочник.Единицы": "ns1:КлючевыеСвойстваЕдиницаИзмерения",
    "Справочник.Склады": "ns1:КлючевыеСвойстваСклад",
    "Справочник.Кассы": "ns1:КлючевыеСвойстваКассаККМ",
    "Справочник.СтатьиЗатрат": "ns1:КлючевыеСвойстваСтатьяРасходов",
    "Справочник.Подразделения": "ns1:КлючевыеСвойстваПодразделение",
    "Справочник.Сотрудники": "ns1:КлючевыеСвойстваПользователь",
    "Справочник.ФизическиеЛица": "ns1:КлючевыеСвойстваФизическоеЛицо",
    "Справочник.Проекты": "tns:КлючевыеСвойстваПроект",
    "Справочник.БанковскиеСчета": "ns1:КлючевыеСвойстваБанковскийСчет",
    "Справочник.Банки": "ns1:КлючевыеСвойстваБанк",
    "Справочник.ТипПродажи": "tns:КлючевыеСвойстваТипыПродаж",
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(name):
    out = []
    for ch in name:
        low = ch.lower()
        if low in TRANSLIT:
            out.append(TRANSLIT[low])
        elif low.isalnum() or low == "_":
            out.append(low)
        else:
            out.append("_")
    return "".join(out)


# ----------------------------------------------------------------------------
# Загрузка описания
# ----------------------------------------------------------------------------

def load_meta():
    with io.open(JSON_PATH, encoding="utf-8-sig") as f:
        return json.load(f)


def std_names(obj):
    return {a["Имя"] for a in obj.get("СтандартныеРеквизиты", [])}


def single_type(attr):
    t = attr.get("Тип") or {}
    types = t.get("Типы") or []
    if t.get("Составной") or len(types) != 1:
        return None
    return types[0]


# ----------------------------------------------------------------------------
# Генерация XSD
# ----------------------------------------------------------------------------

class Gen:
    def __init__(self, meta):
        self.meta = meta
        self.objects = [o for o in meta["Объекты"] if o.get("Выгружать", True)]
        self.by_name = {o["ПолноеИмя"]: o for o in self.objects}
        # generated = все объекты без ручных обработчиков и попутной выгрузки
        self.generated = [
            o for o in self.objects
            if o["ПолноеИмя"] not in MANUAL_ROWS and o["ПолноеИмя"] not in SIDE_WRITTEN
        ]
        self.gen_names = {o["ПолноеИмя"] for o in self.generated
                          if o["Тип"] in ("Справочник", "Документ")}
        self.existing_xsd_names = self._manual_zone_names()
        self.warnings = []

    def _manual_zone_names(self):
        text = XSD_PATH.read_text(encoding="utf-8-sig")
        manual_zone = text.split(XSD_BEGIN)[0]
        return set(re.findall(r'name="([^"]+)"', manual_zone))

    # -- Правила соответствия типов --------------------------------------

    def field_xsd_type(self, attr):
        """Возвращает (тип XSD, режим BSL) для реквизита."""
        st = single_type(attr)
        if st is None:
            return "xs:string", "composite"  # составной -> строкой (XMLСтрока)
        if not st.get("Ссылочный"):
            prim = st.get("ИмяТипа")
            if prim == "Строка":
                return "xs:string", "simple"
            if prim == "Число":
                return "xs:decimal", "simple"
            if prim == "Булево":
                return "xs:boolean", "boolean"
            if prim == "Дата":
                return "xs:dateTime", "simple"
            self.warnings.append("Тип '%s' у '%s' не выгружается — поле пропущено"
                                 % (prim, attr["Имя"]))
            return "", "skip"
        target = st.get("ОбъектМетаданных", "")
        if target.startswith("Перечисление."):
            return "xs:string", "composite"  # имя значения через XMLСтрока
        if target in REF_MANUAL:
            return REF_MANUAL[target], "ref_manual"
        if target in self.gen_names:
            kind, name = target.split(".", 1)
            return "tns:КлючевыеСвойства" + name, "ref_generated:" + name
        return "xs:string", "composite"  # прочие ссылки -> GUID через XMLСтрока

    # -- XSD ---------------------------------------------------------------

    def xsd_section(self):
        L = []
        emitted = set(self.existing_xsd_names)

        def emit_type(name, body_lines):
            if name in emitted:
                self.warnings.append("Тип '%s' уже есть в ручной зоне XSD — генерация пропущена" % name)
                return
            emitted.add(name)
            L.extend(body_lines)

        def element(name, xsd_type, min0=True, extra=""):
            opt = ' minOccurs="0"' if min0 else ""
            typ = ' type="%s"' % xsd_type if xsd_type else ""
            return '\t\t\t<xs:element name="%s"%s%s%s/>' % (name, typ, extra, opt)

        for o in self.generated:
            kind = o["Тип"]
            name = o["Имя"]
            full = o["ПолноеИмя"]

            if kind in ("Справочник", "Документ"):
                ref_simple = ("СправочникСсылка." if kind == "Справочник" else "ДокументСсылка.") + name
                emit_type(ref_simple, [
                    '\t<xs:simpleType name="%s">' % ref_simple,
                    '\t\t<xs:restriction base="ns2:Ref"/>',
                    '\t</xs:simpleType>',
                ])

                std = std_names(o)
                kc_name = "КлючевыеСвойства" + name
                kc = ['\t<xs:complexType name="%s">' % kc_name, "\t\t<xs:sequence>"]
                kc.append(element("Ссылка", "tns:" + ref_simple))
                if kind == "Справочник":
                    if "Наименование" in std:
                        kc.append(element("Наименование", "xs:string"))
                    if "Код" in std:
                        kc.append(element("КодВПрограмме", "xs:string"))
                else:
                    kc.append(element("Дата", "xs:dateTime"))
                    kc.append(element("Номер", "xs:string"))
                kc += ["\t\t</xs:sequence>", "\t</xs:complexType>"]
                emit_type(kc_name, kc)

                obj = ['\t<xs:complexType name="%s">' % full, "\t\t<xs:sequence>"]
                obj.append(element("КлючевыеСвойства", "tns:" + kc_name, min0=False))
                if "Владелец" in std:
                    owner = next(a for a in o["СтандартныеРеквизиты"] if a["Имя"] == "Владелец")
                    xsd_type, _ = self.field_xsd_type(owner)
                    obj.append(element("Владелец", xsd_type))
                for a in o.get("Реквизиты", []):
                    xsd_type, mode = self.field_xsd_type(a)
                    if mode == "skip":
                        continue
                    obj.append(element(a["Имя"], xsd_type))
                for ts in o.get("ТабличныеЧасти", []):
                    obj.append(element(ts["Имя"], "tns:%s.%s" % (full, ts["Имя"])))
                if "ПометкаУдаления" in std:
                    obj.append(element("ПометкаУдаления", "xs:boolean"))
                obj += [
                    '\t\t\t<xs:any namespace="##any" processContents="lax" minOccurs="0" maxOccurs="unbounded"/>',
                    "\t\t</xs:sequence>",
                    '\t\t<xs:anyAttribute namespace="##any" processContents="lax"/>',
                    "\t</xs:complexType>",
                ]
                emit_type(full, obj)

                for ts in o.get("ТабличныеЧасти", []):
                    cont_name = "%s.%s" % (full, ts["Имя"])
                    row_name = cont_name + ".Строка"
                    emit_type(cont_name, [
                        '\t<xs:complexType name="%s">' % cont_name,
                        "\t\t<xs:sequence>",
                        '\t\t\t<xs:element name="Строка" type="tns:%s" minOccurs="0" maxOccurs="unbounded"/>' % row_name,
                        "\t\t</xs:sequence>",
                        "\t</xs:complexType>",
                    ])
                    row = ['\t<xs:complexType name="%s">' % row_name, "\t\t<xs:sequence>"]
                    row.append(element("НомерСтрокиДокумента", "xs:decimal"))
                    for a in ts.get("Реквизиты", []):
                        xsd_type, mode = self.field_xsd_type(a)
                        if mode == "skip":
                            continue
                        row.append(element(a["Имя"], xsd_type))
                    row += [
                        '\t\t\t<xs:any namespace="##any" processContents="lax" minOccurs="0" maxOccurs="unbounded"/>',
                        "\t\t</xs:sequence>",
                        '\t\t<xs:anyAttribute namespace="##any" processContents="lax"/>',
                        "\t</xs:complexType>",
                    ]
                    emit_type(row_name, row)

            elif kind == "РегистрНакопления":
                cont_name = full
                row_name = full + ".Строка"
                emit_type(cont_name, [
                    '\t<xs:complexType name="%s">' % cont_name,
                    "\t\t<xs:sequence>",
                    '\t\t\t<xs:element name="Строка" type="tns:%s" minOccurs="0" maxOccurs="unbounded"/>' % row_name,
                    "\t\t</xs:sequence>",
                    "\t</xs:complexType>",
                ])
                row = ['\t<xs:complexType name="%s">' % row_name, "\t\t<xs:sequence>"]
                row.append(element("Период", "xs:dateTime", min0=False))
                row.append(element("Регистратор", "xs:string"))
                row.append(element("РегистраторТип", "xs:string"))
                if o.get("ВидРегистра") == "Остатки":
                    row.append(element("ВидДвижения", "xs:string"))
                for a in o.get("Измерения", []) + o.get("Ресурсы", []) + o.get("Реквизиты", []):
                    xsd_type, mode = self.field_xsd_type(a)
                    if mode == "skip":
                        continue
                    row.append(element(a["Имя"], xsd_type))
                row += [
                    '\t\t\t<xs:any namespace="##any" processContents="lax" minOccurs="0" maxOccurs="unbounded"/>',
                    "\t\t</xs:sequence>",
                    '\t\t<xs:anyAttribute namespace="##any" processContents="lax"/>',
                    "\t</xs:complexType>",
                ]
                emit_type(row_name, row)

        return "\n".join(L)

    # -- BSL ---------------------------------------------------------------

    def bsl_field(self, mode, target_obj, target_field, xdto_obj, name):
        """Строки заполнения одного поля XDTO."""
        src = "%s.%s" % (target_obj, target_field)
        if mode == "simple":
            return ["\tУстановитьДанные(%s, \"%s\", %s);" % (xdto_obj, name, src)]
        if mode == "boolean":
            return ["\t%s.%s = %s;" % (xdto_obj, name, src)]
        if mode == "composite":
            return [
                "\tЕсли ЗначениеЗаполнено(%s) Тогда" % src,
                "\t\tУстановитьДанные(%s, \"%s\", XMLСтрока(%s));" % (xdto_obj, name, src),
                "\tКонецЕсли;",
            ]
        if mode == "ref_manual":
            return ["\tУстановитьДанные(%s, \"%s\", ПолучитьКлючевоеСвойство(%s, ФайлОбмена, КЭШ, Ссылка));"
                    % (xdto_obj, name, src)]
        if mode.startswith("ref_generated:"):
            fn = "КлючевоеСвойствоГен_" + mode.split(":", 1)[1]
            return ["\tУстановитьДанные(%s, \"%s\", %s(%s));" % (xdto_obj, name, fn, src)]
        return []

    def bsl_section(self):
        L = []
        L.append("// Сгенерировано по metadata_selected_cleaned.json")
        L.append("// Конфигурация: %s, версия %s, дамп от %s" % (
            self.meta.get("ИмяКонфигурации", "?"),
            self.meta.get("ВерсияКонфигурации", "?"),
            self.meta.get("ДатаВыгрузки", "?")))
        L.append("")

        # --- ОписаниеВыгрузки ---
        L.append("Функция НоваяСтрокаОписанияДХ(ИмяМетаданных, Entity, ИмяФайла, Проводимый, Отбор, ВидИсточника)")
        L.append("\tСтрока = Новый Структура;")
        for f in ("ИмяМетаданных", "Entity", "ИмяФайла", "Проводимый", "Отбор", "ВидИсточника"):
            L.append("\tСтрока.Вставить(\"%s\", %s);" % (f, f))
        L.append("\tВозврат Строка;")
        L.append("КонецФункции")
        L.append("")
        L.append("Функция ОписаниеВыгрузки() Экспорт")
        L.append("")
        L.append("\tОписание = Новый Массив;")
        L.append("")

        rows = []
        for o in self.objects:
            full = o["ПолноеИмя"]
            if full in MANUAL_ROWS:
                for r in MANUAL_ROWS[full]:
                    rows.append((full, r["entity"], r["file"], r["posted"], r["selection"], "Объект"))
                continue
            kind = o["Тип"]
            name = o["Имя"]
            fname = translit(name) + ".xml"
            if kind == "РегистрНакопления":
                rows.append((full, name, fname, False, "Все", "РегистрНакопления"))
            else:
                std = std_names(o)
                posted = kind == "Документ" and "Проведен" in std
                selection = "Элементы" if (kind == "Справочник" and "ЭтоГруппа" in std) else "Все"
                rows.append((full, name, fname, posted, selection, "Объект"))

        seen_entities, seen_files = set(), set()
        for full, entity, fname, posted, selection, source in rows:
            if entity in seen_entities:
                raise SystemExit("Дубль entity: " + entity)
            if fname in seen_files:
                raise SystemExit("Дубль файла: " + fname)
            seen_entities.add(entity)
            seen_files.add(fname)
            L.append("\tОписание.Добавить(НоваяСтрокаОписанияДХ(\"%s\", \"%s\", \"%s\", %s, \"%s\", \"%s\"));"
                     % (full, entity, fname, "Истина" if posted else "Ложь", selection, source))
        L.append("")
        L.append("\tВозврат Описание;")
        L.append("")
        L.append("КонецФункции // ОписаниеВыгрузки()")
        L.append("")

        # --- Ключевые свойства генерируемых объектов ---
        for o in self.generated:
            if o["Тип"] not in ("Справочник", "Документ"):
                continue
            name = o["Имя"]
            std = std_names(o)
            L.append("Функция КлючевоеСвойствоГен_%s(Ссылка)" % name)
            L.append("\tЕсли НЕ ЗначениеЗаполнено(Ссылка) Тогда")
            L.append("\t\tВозврат \"\";")
            L.append("\tКонецЕсли;")
            L.append("\tКС = СоздатьЗначениеXDTO(\"КлючевыеСвойства%s\");" % name)
            L.append("\tКС.Ссылка = \"\" + Ссылка.УникальныйИдентификатор();")
            if o["Тип"] == "Справочник":
                if "Наименование" in std:
                    L.append("\tУстановитьДанные(КС, \"Наименование\", Ссылка.Наименование);")
                if "Код" in std:
                    L.append("\tУстановитьДанные(КС, \"КодВПрограмме\", Строка(Ссылка.Код));")
            else:
                L.append("\tУстановитьДанные(КС, \"Дата\", Ссылка.Дата);")
                L.append("\tУстановитьДанные(КС, \"Номер\", Строка(Ссылка.Номер));")
            L.append("\tВозврат КС;")
            L.append("КонецФункции")
            L.append("")

        # --- ПолучитьДанные_Ген_* ---
        for o in self.generated:
            if o["Тип"] not in ("Справочник", "Документ"):
                continue
            name = o["Имя"]
            full = o["ПолноеИмя"]
            std = std_names(o)
            L.append("Функция ПолучитьДанные_Ген_%s(Ссылка, ФайлОбмена, КЭШ)" % name)
            L.append("")
            L.append("\tОбъект = Ссылка.ПолучитьОбъект();")
            L.append("")
            L.append("\tДанныеXDTO = СоздатьЗначениеXDTO(\"%s\");" % full)
            L.append("\tДанныеXDTO.КлючевыеСвойства = КлючевоеСвойствоГен_%s(Ссылка);" % name)
            L.append("")
            if "Владелец" in std:
                owner = next(a for a in o["СтандартныеРеквизиты"] if a["Имя"] == "Владелец")
                _, mode = self.field_xsd_type(owner)
                L += self.bsl_field(mode, "Объект", "Владелец", "ДанныеXDTO", "Владелец")
            for a in o.get("Реквизиты", []):
                _, mode = self.field_xsd_type(a)
                L += self.bsl_field(mode, "Объект", a["Имя"], "ДанныеXDTO", a["Имя"])
            if "ПометкаУдаления" in std:
                L.append("\tЕсли Объект.ПометкаУдаления Тогда")
                L.append("\t\tДанныеXDTO.ПометкаУдаления = Истина;")
                L.append("\tКонецЕсли;")
            for ts in o.get("ТабличныеЧасти", []):
                ts_name = ts["Имя"]
                L.append("")
                L.append("\tСтрокиТЧ = СоздатьЗначениеXDTO(\"%s.%s\");" % (full, ts_name))
                L.append("\tНомерСтроки = 0;")
                L.append("\tДля Каждого СтрокаТЧ Из Объект.%s Цикл" % ts_name)
                L.append("\t\tСтрокаXDTO = СоздатьЗначениеXDTO(\"%s.%s.Строка\");" % (full, ts_name))
                L.append("\t\tНомерСтроки = НомерСтроки + 1;")
                L.append("\t\tСтрокаXDTO.НомерСтрокиДокумента = НомерСтроки;")
                for a in ts.get("Реквизиты", []):
                    _, mode = self.field_xsd_type(a)
                    for line in self.bsl_field(mode, "СтрокаТЧ", a["Имя"], "СтрокаXDTO", a["Имя"]):
                        L.append("\t" + line)
                L.append("\t\tСтрокиТЧ.Строка.Добавить(СтрокаXDTO);")
                L.append("\tКонецЦикла;")
                L.append("\tУстановитьДанные(ДанныеXDTO, \"%s\", СтрокиТЧ);" % ts_name)
            L.append("")
            L.append("\tВозврат ДанныеXDTO;")
            L.append("")
            L.append("КонецФункции // ПолучитьДанные_Ген_%s()" % name)
            L.append("")

        # --- Выгрузка регистров ---
        for o in self.generated:
            if o["Тип"] != "РегистрНакопления":
                continue
            name = o["Имя"]
            full = o["ПолноеИмя"]
            L.append("Функция ВыгрузитьРегистр_Ген_%s(ФайлОбмена, КЭШ, Полная, НачалоПериода, КонецПериода)" % name)
            L.append("")
            L.append("\tЗапрос = Новый Запрос;")
            L.append("\tЕсли Полная Тогда")
            L.append("\t\tЗапрос.Текст = \"ВЫБРАТЬ * ИЗ %s КАК Т\";" % full)
            L.append("\tИначе")
            L.append("\t\tЗапрос.Текст = \"ВЫБРАТЬ * ИЗ %s КАК Т ГДЕ Т.Период МЕЖДУ &НачалоПериода И &КонецПериода\";" % full)
            L.append("\t\tЗапрос.УстановитьПараметр(\"НачалоПериода\", НачалоПериода);")
            L.append("\t\tЗапрос.УстановитьПараметр(\"КонецПериода\", КонецПериода);")
            L.append("\tКонецЕсли;")
            L.append("")
            L.append("\tВыборка = Запрос.Выполнить().Выбрать();")
            L.append("\tКоличество = 0;")
            L.append("")
            L.append("\tПока Выборка.Следующий() Цикл")
            L.append("")
            L.append("\t\tСтрокаXDTO = СоздатьЗначениеXDTO(\"%s.Строка\");" % full)
            L.append("\t\tСтрокаXDTO.Период = Выборка.Период;")
            L.append("\t\tЕсли ЗначениеЗаполнено(Выборка.Регистратор) Тогда")
            L.append("\t\t\tУстановитьДанные(СтрокаXDTO, \"Регистратор\", XMLСтрока(Выборка.Регистратор));")
            L.append("\t\t\tУстановитьДанные(СтрокаXDTO, \"РегистраторТип\", Выборка.Регистратор.Метаданные().ПолноеИмя());")
            L.append("\t\tКонецЕсли;")
            if o.get("ВидРегистра") == "Остатки":
                L.append("\t\tУстановитьДанные(СтрокаXDTO, \"ВидДвижения\", Строка(Выборка.ВидДвижения));")
            for a in o.get("Измерения", []) + o.get("Ресурсы", []) + o.get("Реквизиты", []):
                _, mode = self.field_xsd_type(a)
                src_mode = mode
                # у регистров нет переменной Ссылка для контекста ПолучитьКлючевоеСвойство
                for line in self.bsl_field(src_mode, "Выборка", a["Имя"], "СтрокаXDTO", a["Имя"]):
                    L.append("\t" + line.replace(", КЭШ, Ссылка)", ", КЭШ, Неопределено)"))
            L.append("")
            L.append("\t\tЗаписатьОбъектXDTO(ФайлОбмена, СтрокаXDTO);")
            L.append("\t\tКоличество = Количество + 1;")
            L.append("")
            L.append("\tКонецЦикла;")
            L.append("")
            L.append("\tВозврат Количество;")
            L.append("")
            L.append("КонецФункции // ВыгрузитьРегистр_Ген_%s()" % name)
            L.append("")

        # --- Диспетчер объектов ---
        L.append("Функция ПолучитьДанныеГенерируемогоОбъекта(Ссылка, ФайлОбмена, КЭШ, ДанныеXDTO)")
        L.append("")
        first = True
        for o in self.generated:
            if o["Тип"] not in ("Справочник", "Документ"):
                continue
            kind_ref = "СправочникСсылка." if o["Тип"] == "Справочник" else "ДокументСсылка."
            kw = "Если" if first else "ИначеЕсли"
            first = False
            L.append("\t%s ТипЗнч(Ссылка) = Тип(\"%s%s\") Тогда" % (kw, kind_ref, o["Имя"]))
            L.append("\t\tДанныеXDTO = ПолучитьДанные_Ген_%s(Ссылка, ФайлОбмена, КЭШ);" % o["Имя"])
            L.append("\t\tВозврат Истина;")
        for full in sorted(SIDE_WRITTEN):
            if full not in self.by_name:
                continue
            name = full.split(".", 1)[1]
            kw = "Если" if first else "ИначеЕсли"
            first = False
            L.append("\t%s ТипЗнч(Ссылка) = Тип(\"СправочникСсылка.%s\") Тогда" % (kw, name))
            L.append("\t\t// Объект целиком формирует и записывает СоздатьКлючевоеСвойство_*")
            L.append("\t\tПолучитьКлючевоеСвойство(Ссылка, ФайлОбмена, КЭШ, Ссылка);")
            L.append("\t\tВозврат Ложь; // объект уже записан, основному циклу писать нечего")
        if not first:
            L.append("\tКонецЕсли;")
        L.append("")
        L.append("\tВозврат Ложь;")
        L.append("")
        L.append("КонецФункции // ПолучитьДанныеГенерируемогоОбъекта()")
        L.append("")

        # --- Диспетчер регистров ---
        L.append("Функция ВыгрузитьРегистрГен(ИмяМетаданных, ФайлОбмена, Полная, НачалоПериода, КонецПериода)")
        L.append("")
        L.append("\tКЭШ = Новый Структура;")
        L.append("")
        first = True
        for o in self.generated:
            if o["Тип"] != "РегистрНакопления":
                continue
            kw = "Если" if first else "ИначеЕсли"
            first = False
            L.append("\t%s ИмяМетаданных = \"%s\" Тогда" % (kw, o["ПолноеИмя"]))
            L.append("\t\tВозврат ВыгрузитьРегистр_Ген_%s(ФайлОбмена, КЭШ, Полная, НачалоПериода, КонецПериода);" % o["Имя"])
        if not first:
            L.append("\tКонецЕсли;")
        L.append("")
        L.append("\tВозврат 0;")
        L.append("")
        L.append("КонецФункции // ВыгрузитьРегистрГен()")

        return "\n".join(L)


# ----------------------------------------------------------------------------
# Замена секций между маркерами
# ----------------------------------------------------------------------------

def replace_between(path, begin_marker, end_marker, new_body):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    lines = text.splitlines(keepends=True)
    b_idx = e_idx = None
    for i, line in enumerate(lines):
        if begin_marker in line and b_idx is None:
            b_idx = i
        elif end_marker in line and b_idx is not None:
            e_idx = i
            break
    if b_idx is None or e_idx is None:
        raise SystemExit("Маркеры не найдены в " + str(path))
    eol = "\r\n" if lines[b_idx].endswith("\r\n") else "\n"
    body_lines = [l + eol for l in new_body.split("\n")]
    out = "".join(lines[:b_idx + 1]) + "".join(body_lines) + "".join(lines[e_idx:])
    data = out.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def main():
    meta = load_meta()
    gen = Gen(meta)

    replace_between(XSD_PATH, XSD_BEGIN, XSD_END, gen.xsd_section())
    replace_between(BSL_PATH, BSL_BEGIN, BSL_END, gen.bsl_section())

    n_gen_obj = sum(1 for o in gen.generated if o["Тип"] in ("Справочник", "Документ"))
    n_gen_reg = sum(1 for o in gen.generated if o["Тип"] == "РегистрНакопления")
    print("Объектов в описании: %d" % len(gen.objects))
    print("Ручные обработчики: %d, попутная выгрузка: %d" % (
        sum(1 for o in gen.objects if o["ПолноеИмя"] in MANUAL_ROWS),
        sum(1 for o in gen.objects if o["ПолноеИмя"] in SIDE_WRITTEN)))
    print("Сгенерировано: %d объектов, %d регистров" % (n_gen_obj, n_gen_reg))
    for w in gen.warnings:
        print("ВНИМАНИЕ: " + w)


if __name__ == "__main__":
    sys.exit(main())
