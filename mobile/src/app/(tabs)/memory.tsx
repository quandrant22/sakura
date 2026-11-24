/**
 * Memory Screen — долговременная память Сакуры и база фактов.
 */

import { useRouter } from 'expo-router';
import { ArrowLeft, Brain, Search, Trash2 } from 'lucide-react-native';
import React, { useEffect, useState } from 'react';
import {
  Alert,
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MemoryItem } from '../../api/types';
import { GlassCard } from '../../components/ui/GlassCard';
import { SakuraColors } from '../../constants/colors';
import { useMemoryStore } from '../../stores/useMemoryStore';

const CATEGORIES = [
  { key: '', label: 'Все' },
  { key: 'preferences', label: 'Предпочтения' },
  { key: 'facts', label: 'Факты' },
  { key: 'bookmarks', label: 'Закладки' },
];

export default function MemoryScreen() {
  const router = useRouter();
  const { items, isLoading, category, fetchMemories, search, deleteItem, setCategory } =
    useMemoryStore();

  const [searchText, setSearchText] = useState('');

  useEffect(() => {
    fetchMemories();
  }, [fetchMemories]);

  const handleSearch = (text: string) => {
    setSearchText(text);
    search(text);
  };

  const handleDelete = (id: string) => {
    if (Platform.OS === 'web') {
      deleteItem(id);
      return;
    }
    Alert.alert('Удалить запись', 'Сакура забудет этот факт. Удалить?', [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Удалить', style: 'destructive', onPress: () => deleteItem(id) },
    ]);
  };

  const renderItem = ({ item }: { item: MemoryItem }) => (
    <GlassCard style={styles.card}>
      <View style={styles.cardHeader}>
        <View style={styles.categoryBadge}>
          <Text style={styles.categoryText}>{item.category || 'память'}</Text>
        </View>
        <Pressable onPress={() => handleDelete(item.id)} style={styles.deleteButton}>
          <Trash2 size={14} color={SakuraColors.inkDim} />
        </Pressable>
      </View>
      <Text style={styles.itemText}>{item.text}</Text>
      {item.ts ? (
        <Text style={styles.dateText}>{new Date(item.ts * 1000).toLocaleDateString()}</Text>
      ) : null}
    </GlassCard>
  );

  return (
    <SafeAreaView style={styles.safeArea} edges={['top']}>
      <View style={styles.container}>
        <View style={styles.pageHeader}>
          <Pressable
            style={{ padding: 4 }}
            onPress={() => router.push('/(tabs)/widgets' as any)}>
            <ArrowLeft size={20} color={SakuraColors.ink} />
          </Pressable>
          <Brain size={22} color={SakuraColors.accent} />
          <Text style={styles.title}>Память и факты</Text>
        </View>

        <View style={styles.searchBox}>
          <Search size={16} color={SakuraColors.inkDim} />
          <TextInput
            style={styles.searchInput}
            placeholder="Поиск по воспоминаниям…"
            placeholderTextColor={SakuraColors.textMuted}
            value={searchText}
            onChangeText={handleSearch}
          />
        </View>

        <View style={styles.categoryRow}>
          {CATEGORIES.map((c) => {
            const active = category === c.key;
            return (
              <Pressable
                key={c.key}
                style={[styles.categoryTab, active && styles.categoryTabActive]}
                onPress={() => setCategory(c.key)}>
                <Text style={[styles.categoryTabText, active && styles.categoryTabTextActive]}>
                  {c.label}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <FlatList
          data={items}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={isLoading}
              onRefresh={() => fetchMemories(category)}
              tintColor={SakuraColors.accent}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>Нет сохранённых записей</Text>
            </View>
          }
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: 'transparent',
  },
  container: {
    flex: 1,
    padding: 14,
  },
  pageHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 4,
    marginBottom: 12,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: SakuraColors.ink,
  },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: SakuraColors.panel2,
    borderRadius: 14,
    paddingHorizontal: 14,
    borderWidth: 1,
    borderColor: SakuraColors.line,
    marginBottom: 12,
  },
  searchInput: {
    flex: 1,
    color: SakuraColors.ink,
    paddingVertical: 10,
    fontSize: 14,
  },
  categoryRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 14,
  },
  categoryTab: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: SakuraColors.panel,
    borderWidth: 1,
    borderColor: SakuraColors.line,
  },
  categoryTabActive: {
    backgroundColor: SakuraColors.accentSoft,
    borderColor: SakuraColors.borderAccent,
  },
  categoryTabText: {
    fontSize: 12,
    color: SakuraColors.inkDim,
    fontWeight: '600',
  },
  categoryTabTextActive: {
    color: SakuraColors.accent,
  },
  list: {
    gap: 12,
    paddingBottom: 24,
  },
  card: {
    gap: 8,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  categoryBadge: {
    backgroundColor: SakuraColors.cyanMuted,
    paddingHorizontal: 9,
    paddingVertical: 2,
    borderRadius: 999,
  },
  categoryText: {
    fontSize: 10.5,
    fontWeight: '600',
    color: SakuraColors.cyan,
  },
  deleteButton: {
    padding: 4,
  },
  itemText: {
    fontSize: 14,
    color: SakuraColors.ink,
    lineHeight: 20,
  },
  dateText: {
    fontSize: 10.5,
    color: SakuraColors.textMuted,
    alignSelf: 'flex-end',
  },
  empty: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  emptyText: {
    color: SakuraColors.inkDim,
    fontSize: 13.5,
  },
});
