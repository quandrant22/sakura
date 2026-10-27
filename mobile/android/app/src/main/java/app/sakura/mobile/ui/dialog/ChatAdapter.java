package app.sakura.mobile.ui.dialog;

import android.view.Gravity;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;

import app.sakura.mobile.R;
import app.sakura.mobile.ui.Motion;
import app.sakura.mobile.ui.model.Models;

/** Пузыри чата: у Сакуры — градиент, у Мастера — panel2; метка канала и устройства. */
final class ChatAdapter extends RecyclerView.Adapter<RecyclerView.ViewHolder> {
    private static final int TYPE_MORE = 0;
    private static final int TYPE_MSG = 1;

    private final List<Models.Message> items = new ArrayList<>();
    private boolean hasMore;
    private int animateFrom = Integer.MAX_VALUE;
    private Runnable onMore;
    private Consumer<Models.Message> onLongPress;

    void setCallbacks(Runnable onMore, Consumer<Models.Message> onLongPress) {
        this.onMore = onMore;
        this.onLongPress = onLongPress;
    }

    /** animateNew — анимировать появление добавленных в конец (push), но не загрузку истории. */
    void submit(List<Models.Message> list, boolean more, boolean animateNew) {
        int before = items.size();
        items.clear();
        items.addAll(list);
        hasMore = more;
        animateFrom = animateNew && items.size() > before ? before : Integer.MAX_VALUE;
        notifyDataSetChanged();
    }

    List<Models.Message> items() {
        return items;
    }

    private int offset() {
        return hasMore ? 1 : 0;
    }

    @Override
    public int getItemCount() {
        return items.size() + offset();
    }

    @Override
    public int getItemViewType(int position) {
        return hasMore && position == 0 ? TYPE_MORE : TYPE_MSG;
    }

    @NonNull
    @Override
    public RecyclerView.ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        LayoutInflater inf = LayoutInflater.from(parent.getContext());
        if (viewType == TYPE_MORE) {
            View v = inf.inflate(R.layout.item_load_more, parent, false);
            return new RecyclerView.ViewHolder(v) { };
        }
        return new Bubble(inf.inflate(R.layout.item_bubble, parent, false));
    }

    @Override
    public void onBindViewHolder(@NonNull RecyclerView.ViewHolder holder, int position) {
        if (holder.getItemViewType() == TYPE_MORE) {
            holder.itemView.findViewById(R.id.load_more).setOnClickListener(v -> {
                if (onMore != null) {
                    onMore.run();
                }
            });
            return;
        }
        int i = position - offset();
        Models.Message m = items.get(i);
        ((Bubble) holder).bind(m);
        holder.itemView.setOnLongClickListener(v -> {
            if (onLongPress != null && !m.pending) {
                onLongPress.accept(m);
            }
            return true;
        });
        if (i >= animateFrom) {
            Motion.bubbleIn(((Bubble) holder).bubble);
        }
    }

    static final class Bubble extends RecyclerView.ViewHolder {
        final LinearLayout row;
        final LinearLayout bubble;
        final TextView text;
        final TextView meta;

        static int dim(TextView v) {
            android.util.TypedValue tv = new android.util.TypedValue();
            v.getContext().getTheme().resolveAttribute(R.attr.sakuraInkDim, tv, true);
            return tv.data;
        }

        Bubble(View v) {
            super(v);
            row = v.findViewById(R.id.row);
            bubble = v.findViewById(R.id.bubble);
            text = v.findViewById(R.id.text);
            meta = v.findViewById(R.id.meta);
        }

        void bind(Models.Message m) {
            boolean master = m.fromMaster();
            row.setGravity(master ? Gravity.END : Gravity.START);
            bubble.setBackgroundResource(master ? R.drawable.bg_bubble_master : R.drawable.bg_bubble_sakura);
            text.setText(m.text);
            String when = m.pending ? "отправляется" : Models.time(m.ts);
            meta.setText(m.label() + " · " + when);
            // на градиенте Сакуры приглушённый текст не читается — берём основной цвет текста
            meta.setTextColor(master ? dim(meta) : text.getCurrentTextColor());
            meta.setAlpha(master ? 1f : 0.8f);
            bubble.setContentDescription((master ? "Вы: " : "Сакура: ") + m.text);
        }
    }
}
